"""Deterministic Benchmark Baseline Strategy (Phase 6C).

Implements the frozen spot, long-only, single-position EMA 9/20 crossover strategy:
- Bullish crossover (EMA9[t-1] <= EMA20[t-1] and EMA9[t] > EMA20[t]):
  - If FLAT: BUY sized by RiskEngine with exact 2% stop-loss based on candle t CLOSE:
    stop_loss = round(candle_t.close * 0.98, 2)
  - If ALREADY LONG: HOLD
- Bearish crossover (EMA9[t-1] >= EMA20[t-1] and EMA9[t] < EMA20[t]):
  - If ALREADY LONG: SELL to close the entire existing position
  - If FLAT: HOLD (no short selling)
- Equality (EMA9[t] == EMA20[t]): HOLD
- Missing data (warmup before index 20): HOLD
- Strictly independent of MarketRegime (TrendRegime / VolatilityRegime).
"""

from __future__ import annotations

import logging
from typing import List, Optional, Sequence, Tuple

from app.indicators.ema import calculate_ema
from app.trading.portfolio import PortfolioTracker
from app.trading.risk import RiskEngine
from app.trading.schemas import OrderRequest, OrderSide
from app.trading.simulation.replay import ReplayContext

logger = logging.getLogger(__name__)

SIGNAL_BUY = "BUY"
SIGNAL_SELL = "SELL"
SIGNAL_HOLD = "HOLD"


class BenchmarkBaselineStrategy:
    """Deterministic EMA 9/20 crossover baseline strategy (Phase 6C).

    Plugs directly into ChronologicalReplayEngine and SimulationClock as a StrategyCallable:
    Callable[[ReplayContext], Sequence[OrderRequest]].
    """

    def __init__(
        self,
        symbol: Optional[str] = None,
        risk_engine: Optional[RiskEngine] = None,
        portfolio: Optional[PortfolioTracker] = None,
    ) -> None:
        """Initialize the benchmark baseline strategy.

        Args:
            symbol: Target trading symbol (defaults to candle's symbol or RELIANCE).
            risk_engine: Optional RiskEngine for sizing and pre-trade checks.
            portfolio: Optional PortfolioTracker for position/cash queries.
        """
        self.symbol: Optional[str] = symbol.strip().upper() if symbol else None
        self.risk_engine: RiskEngine = risk_engine if risk_engine is not None else RiskEngine()
        self.portfolio: Optional[PortfolioTracker] = portfolio

    @staticmethod
    def calculate_stop_loss(close_price: float) -> float:
        """Calculate exact 2% stop-loss reference price based on decision candle Close:

        stop_loss = round(candle_t.close * 0.98, 2)

        Must NOT be calculated from t+1 Open, execution price, or fill price.
        """
        return round(float(close_price) * 0.98, 2)

    @staticmethod
    def evaluate_crossover_values(
        prev_ema9: Optional[float],
        curr_ema9: Optional[float],
        prev_ema20: Optional[float],
        curr_ema20: Optional[float],
    ) -> Optional[str]:
        """Evaluate discrete EMA crossover boundary conditions.

        Args:
            prev_ema9: EMA9 at candle t-1.
            curr_ema9: EMA9 at completed candle t.
            prev_ema20: EMA20 at candle t-1.
            curr_ema20: EMA20 at completed candle t.

        Returns:
            "BUY" for bullish crossover,
            "SELL" for bearish crossover,
            None for HOLD (missing data, equality, or no crossing).
        """
        # If any of the 4 required values is missing: HOLD
        if prev_ema9 is None or curr_ema9 is None or prev_ema20 is None or curr_ema20 is None:
            return None

        # Exact boundary: equality at current candle is NOT a crossover
        if curr_ema9 == curr_ema20:
            return None

        # Bullish crossover: prev_ema9 <= prev_ema20 AND curr_ema9 > curr_ema20
        if prev_ema9 <= prev_ema20 and curr_ema9 > curr_ema20:
            return SIGNAL_BUY

        # Bearish crossover: prev_ema9 >= prev_ema20 AND curr_ema9 < curr_ema20
        if prev_ema9 >= prev_ema20 and curr_ema9 < curr_ema20:
            return SIGNAL_SELL

        return None

    def calculate_crossover(
        self, closes: Sequence[float]
    ) -> Tuple[Optional[str], Optional[float], Optional[float], Optional[float], Optional[float]]:
        """Calculate EMA9 and EMA20 over visible closes and evaluate crossover.

        Args:
            closes: Sequence of completed candle Close prices.

        Returns:
            Tuple of (signal, curr_ema9, prev_ema9, curr_ema20, prev_ema20).
        """
        if len(closes) < 2:
            return None, None, None, None, None

        ema9_series = calculate_ema(closes, period=9)
        ema20_series = calculate_ema(closes, period=20)

        curr_ema9 = ema9_series[-1]
        prev_ema9 = ema9_series[-2]
        curr_ema20 = ema20_series[-1]
        prev_ema20 = ema20_series[-2]

        signal = self.evaluate_crossover_values(
            prev_ema9=prev_ema9,
            curr_ema9=curr_ema9,
            prev_ema20=prev_ema20,
            curr_ema20=curr_ema20,
        )
        return signal, curr_ema9, prev_ema9, curr_ema20, prev_ema20

    def __call__(self, context: ReplayContext) -> List[OrderRequest]:
        """Evaluate strategy signals on completed candle t and emit orders for t+1 Open.

        Enforces all frozen baseline invariants:
        1. SPOT, LONG-ONLY, SINGLE-POSITION.
        2. If FLAT: bullish crossover -> BUY; bearish crossover -> HOLD.
        3. If ALREADY LONG: bullish crossover -> HOLD; bearish crossover -> SELL to close.
        4. Never short sells or scales into an existing position.
        5. Exact 2% stop-loss based on candle t Close: round(candle_t.close * 0.98, 2).
        6. BUY sized deterministically via RiskEngine.calculate_position_size().
        7. Deterministic order ID generation ensuring repeated identical calls produce identical outputs.
        """
        clean_symbol = self.symbol or getattr(context.current_candle, "symbol", None) or "RELIANCE"
        clean_symbol = str(clean_symbol).strip().upper()

        closes = [float(c.close) for c in context.visible_candles]
        signal, _, _, _, _ = self.calculate_crossover(closes)

        if signal is None:
            return []

        # Check existing position state
        pos = context.portfolio_state.positions.get(clean_symbol)
        is_long = pos is not None and pos.is_open and pos.quantity > 0

        # Deterministic timestamp integer for order_id reproducibility
        ts_int = int(context.virtual_time.timestamp())

        # ----------------------------------------------------------------------
        # Case 1: Bullish Crossover Signal
        # ----------------------------------------------------------------------
        if signal == SIGNAL_BUY:
            if is_long:
                # Already long: rule says HOLD (no scaling, no duplicate buy)
                return []

            # FLAT: size and generate BUY order
            close_price = float(context.current_candle.close)
            stop_loss = self.calculate_stop_loss(close_price)

            quantity = self.risk_engine.calculate_position_size(
                symbol=clean_symbol,
                price=close_price,
                stop_loss=stop_loss,
                portfolio=self.portfolio,
                capital=context.portfolio_state.cash,
            )

            if quantity <= 0:
                # Insufficient capital or risk limit breach -> cannot buy -> HOLD
                return []

            order = OrderRequest(
                order_id=f"BASELINE_BUY_{clean_symbol}_{ts_int}",
                symbol=clean_symbol,
                side=OrderSide.BUY,
                quantity=quantity,
                decision_time=context.virtual_time,
                decision_price=close_price,
                stop_loss=stop_loss,
                reason="EMA9_EMA20_BULLISH_CROSSOVER",
            )

            if self.portfolio is not None:
                risk_check = self.risk_engine.validate_order(
                    order=order,
                    portfolio=self.portfolio,
                    current_price=close_price,
                )
                if not risk_check.approved:
                    return []

            return [order]

        # ----------------------------------------------------------------------
        # Case 2: Bearish Crossover Signal
        # ----------------------------------------------------------------------
        if signal == SIGNAL_SELL:
            if not is_long or pos is None:
                # FLAT: rule says HOLD (no short selling allowed in spot baseline)
                return []

            # ALREADY LONG: generate SELL order to close the ENTIRE existing position
            close_price = float(context.current_candle.close)
            order = OrderRequest(
                order_id=f"BASELINE_SELL_{clean_symbol}_{ts_int}",
                symbol=clean_symbol,
                side=OrderSide.SELL,
                quantity=pos.quantity,
                decision_time=context.virtual_time,
                decision_price=close_price,
                reason="EMA9_EMA20_BEARISH_CROSSOVER",
            )

            if self.portfolio is not None:
                risk_check = self.risk_engine.validate_order(
                    order=order,
                    portfolio=self.portfolio,
                    current_price=close_price,
                )
                if not risk_check.approved:
                    return []

            return [order]

        return []
