"""Authoritative Simulation Service and Session Manager (Phase 6D).

Coordinates active simulation sessions, background playback tasks via SimulationClock,
and idempotent database persistence to PostgreSQL.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import models
from app.database.session import async_session_factory
from app.market_data.schema import CandleData
from app.trading.execution import ExecutionConfig, ExecutionEngine
from app.trading.portfolio import PortfolioTracker
from app.trading.risk import RiskConfig, RiskEngine
from app.trading.schemas import (
    PortfolioState,
)
from app.trading.simulation.clock import (
    InvalidStateTransitionError,
    SimulationClock,
    SimulationLifecycleState,
)
from app.trading.simulation.replay import (
    ChronologicalReplayEngine,
    EmptyDatasetError,
    ReplayStepResult,
    load_historical_candles_from_db,
)
from app.trading.simulation.schemas import (
    DecisionResponse,
    PerformanceMetricsResponse,
    SimulationCreateRequest,
    SimulationResponse,
    TradeResponse,
)
from app.trading.strategy.baseline import BenchmarkBaselineStrategy
from app.trading.triggers import TriggerMonitor

logger = logging.getLogger(__name__)


class SimulationSession:
    """Active in-memory runtime session for a historical simulation run."""

    def __init__(
        self,
        simulation_id: str,
        instrument_id: int,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        initial_capital: float,
        is_baseline: bool,
        engine: ChronologicalReplayEngine,
        clock: SimulationClock,
        portfolio: PortfolioTracker,
        risk_engine: RiskEngine,
        execution_engine: ExecutionEngine,
        trigger_monitor: TriggerMonitor,
        strategy: Optional[BenchmarkBaselineStrategy],
        session_factory: async_sessionmaker[AsyncSession],
        created_at: Optional[datetime] = None,
    ) -> None:
        self.simulation_id = simulation_id
        self.instrument_id = instrument_id
        self.symbol = symbol.strip().upper()
        self.timeframe = timeframe
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.is_baseline = is_baseline
        self.engine = engine
        self.clock = clock
        self.portfolio = portfolio
        self.risk_engine = risk_engine
        self.execution_engine = execution_engine
        self.trigger_monitor = trigger_monitor
        self.strategy = strategy
        self.session_factory = session_factory
        self.created_at = created_at or datetime.now(timezone.utc)

        self.sync_lock = asyncio.Lock()
        self.peak_portfolio_value = float(initial_capital)
        self.max_drawdown_pct = 0.0

        # Idempotent persistence tracking sets
        self.persisted_order_ids: Set[str] = set()
        self.persisted_trade_ids: Set[str] = set()
        self.persisted_snapshot_timestamps: Set[datetime] = set()
        self.decisions: List[Dict[str, Any]] = []

    def on_step_event(self, step_res: ReplayStepResult) -> None:
        """Process step results for metrics and decision tracking."""
        port_state = step_res.portfolio_state or self.portfolio.get_state()
        val = port_state.total_portfolio_value

        self.peak_portfolio_value = max(self.peak_portfolio_value, val)

        if self.peak_portfolio_value > 0:
            dd = (self.peak_portfolio_value - val) / self.peak_portfolio_value
            dd_pct = dd * 100.0
            if dd_pct > self.max_drawdown_pct:
                self.max_drawdown_pct = round(dd_pct, 4)

        # Record decision event for this candle step
        if self.is_baseline:
            if step_res.strategy_orders_queued:
                for o in step_res.strategy_orders_queued:
                    self.decisions.append(
                        {
                            "id": f"dec_{self.simulation_id}_{step_res.step_index}_{o.order_id[:8]}",
                            "simulation_id": self.simulation_id,
                            "candle_timestamp": step_res.timestamp.isoformat(),
                            "action": o.side.value,
                            "confidence": 1.0,
                            "quantity": o.quantity,
                            "stop_loss": o.stop_loss,
                            "take_profit": o.take_profit,
                            "reason": o.reason or "EMA 9/20 crossover signal",
                            "market_regime": None,
                        }
                    )
            else:
                self.decisions.append(
                    {
                        "id": f"dec_{self.simulation_id}_{step_res.step_index}_hold",
                        "simulation_id": self.simulation_id,
                        "candle_timestamp": step_res.timestamp.isoformat(),
                        "action": "HOLD",
                        "confidence": 1.0,
                        "quantity": None,
                        "stop_loss": None,
                        "take_profit": None,
                        "reason": "Hold (no crossover signal)",
                        "market_regime": None,
                    }
                )

    def build_performance_metrics(self, state: Optional[PortfolioState] = None) -> Dict[str, Any]:
        """Compute performance metrics matching Section 58 of specification."""
        st = state or self.portfolio.get_state()
        closed = st.closed_trades
        total_trades = len(closed)
        winning_trades = sum(1 for t in closed if t.net_pnl > 0.0)
        losing_trades = sum(1 for t in closed if t.net_pnl < 0.0)
        win_rate = (winning_trades / total_trades) * 100.0 if total_trades > 0 else 0.0

        wins_total = sum(t.net_pnl for t in closed if t.net_pnl > 0.0)
        losses_total = abs(sum(t.net_pnl for t in closed if t.net_pnl < 0.0))

        avg_win = (wins_total / winning_trades) if winning_trades > 0 else 0.0
        avg_loss = (losses_total / losing_trades) if losing_trades > 0 else 0.0

        if losses_total > 0:
            profit_factor = round(wins_total / losses_total, 4)
        elif wins_total > 0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0

        return {
            "simulation_id": self.simulation_id,
            "initial_capital": round(st.initial_capital, 4),
            "final_portfolio_value": round(st.total_portfolio_value, 4),
            "gross_pnl": round(st.gross_pnl, 4),
            "net_pnl": round(st.net_pnl, 4),
            "total_return_pct": round(st.total_return_pct, 4),
            "transaction_costs": round(st.total_transaction_costs, 4),
            "slippage_cost": round(st.total_slippage_cost, 4),
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate_pct": round(win_rate, 4),
            "average_win": round(avg_win, 4),
            "average_loss": round(avg_loss, 4),
            "profit_factor": profit_factor,
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "exposure_pct": round(st.exposure_pct, 4),
            "open_positions_count": st.open_positions_count,
        }

    async def sync_to_db(self, is_final: bool = False) -> None:
        """Idempotently persist current simulation progress, orders, trades, and snapshots."""
        async with self.sync_lock, self.session_factory() as db:
            try:
                stmt = select(models.SimulationRun).where(
                    models.SimulationRun.id == self.simulation_id
                )
                res = await db.execute(stmt)
                sim_run = res.scalar_one_or_none()
                if sim_run is None:
                    logger.warning(
                        "SimulationRun %s not found in database during sync.",
                        self.simulation_id,
                    )
                    return

                # Update SimulationRun status and financial state
                clock_status = self.clock.get_status()
                sim_run.status = models.SimulationStatus(clock_status.state.value)
                port_state = self.portfolio.get_state()
                sim_run.final_portfolio_value = port_state.total_portfolio_value
                sim_run.total_return_pct = port_state.total_return_pct

                metrics = self.build_performance_metrics(port_state)
                # Keep latest decisions inside metrics JSON for offline querying
                metrics["decisions"] = self.decisions[-200:]
                metrics["current_time"] = (
                    clock_status.current_time.isoformat() if clock_status.current_time else None
                )
                metrics["step_index"] = clock_status.step_index
                metrics["total_candles"] = clock_status.total_candles
                metrics["progress_pct"] = clock_status.progress_pct
                metrics["speed"] = clock_status.speed
                sim_run.metrics = metrics

                # 1. Idempotently insert new Orders
                for exec_res in self.engine.execution_history:
                    if exec_res.order_id not in self.persisted_order_ids:
                        order_side = models.OrderSide[exec_res.side.value]
                        order_status = models.OrderStatus[exec_res.status.value]
                        fill_price = (
                            exec_res.execution_price
                            if exec_res.execution_price is not None
                            else (exec_res.market_price or 0.0)
                        )
                        order_db_id = str(
                            uuid.uuid5(
                                uuid.NAMESPACE_DNS, f"{self.simulation_id}_{exec_res.order_id}"
                            )
                        )
                        db_order = models.Order(
                            id=order_db_id,
                            simulation_id=self.simulation_id,
                            instrument_id=self.instrument_id,
                            order_type=models.OrderType.MARKET,
                            side=order_side,
                            quantity=exec_res.quantity,
                            price=fill_price,
                            status=order_status,
                            reason=exec_res.rejection_reason or "",
                            candle_timestamp=exec_res.decision_time,
                        )
                        db.add(db_order)
                        self.persisted_order_ids.add(exec_res.order_id)

                # 2. Idempotently insert new Trades
                for tr in self.portfolio.closed_trades:
                    if tr.trade_id not in self.persisted_trade_ids:
                        trade_side = models.OrderSide[tr.side.value]
                        db_trade = models.Trade(
                            id=tr.trade_id,
                            simulation_id=self.simulation_id,
                            order_id=None,
                            instrument_id=self.instrument_id,
                            side=trade_side,
                            quantity=tr.quantity,
                            entry_price=tr.entry_price,
                            exit_price=tr.exit_price,
                            gross_pnl=tr.gross_pnl,
                            net_pnl=tr.net_pnl,
                            transaction_costs=tr.transaction_costs,
                            slippage_cost=tr.slippage_cost,
                            is_closed=True,
                            entry_time=tr.entry_time,
                            exit_time=tr.exit_time,
                        )
                        db.add(db_trade)
                        self.persisted_trade_ids.add(tr.trade_id)

                # 3. Idempotently insert PortfolioSnapshot
                cur_time = self.clock.current_time
                if cur_time is not None and cur_time not in self.persisted_snapshot_timestamps:
                    snapshot = models.PortfolioSnapshot(
                        simulation_id=self.simulation_id,
                        timestamp=cur_time,
                        cash=port_state.cash,
                        portfolio_value=port_state.total_portfolio_value,
                        gross_pnl=port_state.gross_pnl,
                        net_pnl=port_state.net_pnl,
                        exposure_pct=port_state.exposure_pct,
                        open_positions_count=port_state.open_positions_count,
                    )
                    db.add(snapshot)
                    self.persisted_snapshot_timestamps.add(cur_time)

                # 4. Sync open positions
                await db.execute(
                    delete(models.Position).where(
                        models.Position.simulation_id == self.simulation_id
                    )
                )
                for pos in port_state.positions.values():
                    db_pos = models.Position(
                        simulation_id=self.simulation_id,
                        instrument_id=self.instrument_id,
                        quantity=pos.quantity,
                        average_entry_price=pos.average_entry_price,
                        current_price=pos.current_price,
                        stop_loss=pos.stop_loss,
                        take_profit=pos.take_profit,
                        unrealized_pnl=pos.unrealized_gross_pnl,
                        is_open=pos.is_open,
                    )
                    db.add(db_pos)

                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception(
                    "Failed to sync simulation %s to database",
                    self.simulation_id,
                )
                raise


class SimulationService:
    """Singleton service managing simulation sessions and API coordination."""

    def __init__(
        self,
        session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
        base_delay: float = 0.05,
    ) -> None:
        self.session_factory = session_factory or async_session_factory
        self.base_delay = base_delay
        self._sessions: Dict[str, SimulationSession] = {}
        self._lock = asyncio.Lock()

    async def create_simulation(
        self,
        db: AsyncSession,
        req: SimulationCreateRequest,
    ) -> SimulationResponse:
        """Create and initialize a new historical simulation run atomically."""
        clean_symbol = req.symbol.strip().upper()

        # Step 1: Validate instrument existence
        stmt = select(models.Instrument).where(models.Instrument.symbol == clean_symbol)
        res = await db.execute(stmt)
        instrument = res.scalar_one_or_none()
        if instrument is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Instrument with symbol '{clean_symbol}' not found in database.",
            )

        # Step 2: Validate and load locked historical candles
        try:
            candles: List[CandleData] = await load_historical_candles_from_db(
                db=db,
                symbol=clean_symbol,
                timeframe=req.timeframe,
                start_date=req.start_date,
                end_date=req.end_date,
            )
        except EmptyDatasetError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

        # Step 3: Instantiate isolated simulation components
        portfolio = PortfolioTracker(initial_capital=req.initial_capital)

        exec_cfg = ExecutionConfig(
            slippage_pct=req.slippage_pct or 0.0005,
            brokerage_rate=req.brokerage_rate or 0.0003,
            fixed_fee_per_order=req.fixed_fee_per_order or 0.0,
        )
        execution_engine = ExecutionEngine(
            config=exec_cfg,
        )

        risk_cfg = RiskConfig(
            max_risk_per_trade=req.max_risk_per_trade or 0.02,
            max_position_exposure=req.max_position_exposure or 0.25,
            max_portfolio_exposure=req.max_portfolio_exposure or 1.00,
            max_daily_loss=req.max_daily_loss or 0.05,
        )
        risk_engine = RiskEngine(config=risk_cfg, execution_config=exec_cfg)

        trigger_monitor = TriggerMonitor(execution_engine=execution_engine)

        strategy: Optional[BenchmarkBaselineStrategy] = None
        if req.is_baseline:
            strategy = BenchmarkBaselineStrategy(
                symbol=clean_symbol,
                risk_engine=risk_engine,
                portfolio=portfolio,
            )

        replay_engine = ChronologicalReplayEngine(
            candles=candles,
            portfolio=portfolio,
            execution_engine=execution_engine,
            risk_engine=risk_engine,
            trigger_monitor=trigger_monitor,
        )

        clock = SimulationClock(
            engine=replay_engine,
            strategy=strategy,
            speed=req.speed,
            base_delay=self.base_delay,
        )

        # Step 4: Atomically persist SimulationRun to PostgreSQL
        sim_run = models.SimulationRun(
            instrument_id=instrument.id,
            timeframe=req.timeframe,
            start_date=req.start_date,
            end_date=req.end_date,
            initial_capital=req.initial_capital,
            final_portfolio_value=req.initial_capital,
            total_return_pct=0.0,
            status=models.SimulationStatus.CREATED,
            is_baseline=req.is_baseline,
            metrics={
                "initial_capital": req.initial_capital,
                "final_portfolio_value": req.initial_capital,
                "total_return_pct": 0.0,
                "speed": req.speed,
                "total_candles": len(candles),
            },
        )
        db.add(sim_run)
        await db.commit()
        await db.refresh(sim_run)

        # Step 5: Instantiate and register runtime session
        session = SimulationSession(
            simulation_id=sim_run.id,
            instrument_id=instrument.id,
            symbol=clean_symbol,
            timeframe=req.timeframe,
            start_date=req.start_date,
            end_date=req.end_date,
            initial_capital=req.initial_capital,
            is_baseline=req.is_baseline,
            engine=replay_engine,
            clock=clock,
            portfolio=portfolio,
            risk_engine=risk_engine,
            execution_engine=execution_engine,
            trigger_monitor=trigger_monitor,
            strategy=strategy,
            session_factory=self.session_factory,
            created_at=sim_run.created_at,
        )

        # Hook step callback for decision, drawdown tracking, and WebSocket event dispatch
        def _step_hook(step_res: ReplayStepResult) -> None:
            session.on_step_event(step_res)
            self._dispatch_step_events(session, step_res)

        clock.on_step = _step_hook

        async with self._lock:
            self._sessions[sim_run.id] = session

        return self._build_simulation_response(session, sim_run)

    async def get_simulation(
        self,
        simulation_id: str,
        db: AsyncSession,
    ) -> SimulationResponse:
        """Get authoritative simulation state from active session or database."""
        async with self._lock:
            session = self._sessions.get(simulation_id)

        if session is not None:
            # Active in memory
            return self._build_simulation_response(session)

        # Check database
        stmt = select(models.SimulationRun).where(models.SimulationRun.id == simulation_id)
        res = await db.execute(stmt)
        sim_run = res.scalar_one_or_none()
        if sim_run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Simulation with ID '{simulation_id}' not found.",
            )

        # Retrieve instrument symbol
        inst_stmt = select(models.Instrument).where(models.Instrument.id == sim_run.instrument_id)
        inst_res = await db.execute(inst_stmt)
        instrument = inst_res.scalar_one_or_none()
        symbol = instrument.symbol if instrument else "UNKNOWN"

        metrics = sim_run.metrics or {}
        step_idx = metrics.get("step_index", 0)
        tot_candles = metrics.get("total_candles", 0)
        prog = metrics.get("progress_pct", 0.0)
        spd = metrics.get("speed", 1.0)
        cur_time_str = metrics.get("current_time")
        cur_time = datetime.fromisoformat(cur_time_str) if cur_time_str else None

        return SimulationResponse(
            id=sim_run.id,
            instrument_id=sim_run.instrument_id,
            symbol=symbol,
            timeframe=sim_run.timeframe,
            start_date=sim_run.start_date,
            end_date=sim_run.end_date,
            initial_capital=sim_run.initial_capital,
            final_portfolio_value=sim_run.final_portfolio_value,
            total_return_pct=sim_run.total_return_pct,
            status=sim_run.status.value,
            is_baseline=sim_run.is_baseline,
            speed=spd,
            current_time=cur_time,
            step_index=step_idx,
            total_candles=tot_candles,
            progress_pct=prog,
            metrics=metrics,
            created_at=sim_run.created_at,
            updated_at=sim_run.updated_at,
        )

    async def start_simulation(
        self,
        simulation_id: str,
        db: AsyncSession,
    ) -> SimulationResponse:
        """Start simulation playback via SimulationClock."""
        session = await self._get_active_session(simulation_id, db)
        try:
            await session.clock.start()
        except InvalidStateTransitionError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

        self._attach_background_completion_handler(session)
        await session.sync_to_db()
        return self._build_simulation_response(session)

    async def pause_simulation(
        self,
        simulation_id: str,
        db: AsyncSession,
    ) -> SimulationResponse:
        """Pause active simulation playback."""
        session = await self._get_active_session(simulation_id, db)
        try:
            await session.clock.pause()
        except InvalidStateTransitionError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

        await session.sync_to_db()
        return self._build_simulation_response(session)

    async def resume_simulation(
        self,
        simulation_id: str,
        db: AsyncSession,
    ) -> SimulationResponse:
        """Resume playback from PAUSED state."""
        session = await self._get_active_session(simulation_id, db)
        try:
            await session.clock.resume()
        except InvalidStateTransitionError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

        self._attach_background_completion_handler(session)
        await session.sync_to_db()
        return self._build_simulation_response(session)

    async def step_simulation(
        self,
        simulation_id: str,
        db: AsyncSession,
    ) -> SimulationResponse:
        """Advance simulation by exactly one candle while PAUSED."""
        session = await self._get_active_session(simulation_id, db)
        try:
            await session.clock.step()
        except InvalidStateTransitionError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

        await session.sync_to_db()
        return self._build_simulation_response(session)

    async def stop_simulation(
        self,
        simulation_id: str,
        db: AsyncSession,
    ) -> SimulationResponse:
        """Stop playback and transition to terminal STOPPED state."""
        session = await self._get_active_session(simulation_id, db)
        try:
            await session.clock.stop()
        except InvalidStateTransitionError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

        await session.sync_to_db(is_final=True)
        self._dispatch_complete_event(session, status="STOPPED")
        return self._build_simulation_response(session)

    async def get_simulation_trades(
        self,
        simulation_id: str,
        db: AsyncSession,
    ) -> List[TradeResponse]:
        """Get authoritative executed trades for a simulation."""
        async with self._lock:
            session = self._sessions.get(simulation_id)

        if session is not None:
            # Active in memory
            return [
                TradeResponse(
                    id=t.trade_id,
                    simulation_id=session.simulation_id,
                    order_id=None,
                    instrument_id=session.instrument_id,
                    symbol=t.symbol,
                    side=t.side.value,
                    quantity=t.quantity,
                    entry_price=t.entry_price,
                    exit_price=t.exit_price,
                    gross_pnl=t.gross_pnl,
                    net_pnl=t.net_pnl,
                    transaction_costs=t.transaction_costs,
                    slippage_cost=t.slippage_cost,
                    is_closed=True,
                    entry_time=t.entry_time,
                    exit_time=t.exit_time,
                )
                for t in session.portfolio.closed_trades
            ]

        # Query database
        stmt_sim = select(models.SimulationRun).where(models.SimulationRun.id == simulation_id)
        res_sim = await db.execute(stmt_sim)
        if res_sim.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Simulation with ID '{simulation_id}' not found.",
            )

        stmt = (
            select(models.Trade, models.Instrument.symbol)
            .join(models.Instrument, models.Trade.instrument_id == models.Instrument.id)
            .where(models.Trade.simulation_id == simulation_id)
            .order_by(models.Trade.entry_time.asc())
        )
        res = await db.execute(stmt)
        rows = res.all()

        return [
            TradeResponse(
                id=tr.id,
                simulation_id=tr.simulation_id,
                order_id=tr.order_id,
                instrument_id=tr.instrument_id,
                symbol=sym,
                side=tr.side.value,
                quantity=tr.quantity,
                entry_price=tr.entry_price,
                exit_price=tr.exit_price,
                gross_pnl=tr.gross_pnl,
                net_pnl=tr.net_pnl,
                transaction_costs=tr.transaction_costs,
                slippage_cost=tr.slippage_cost,
                is_closed=tr.is_closed,
                entry_time=tr.entry_time,
                exit_time=tr.exit_time,
            )
            for tr, sym in rows
        ]

    async def get_simulation_performance(
        self,
        simulation_id: str,
        db: AsyncSession,
    ) -> PerformanceMetricsResponse:
        """Get comprehensive performance metrics."""
        async with self._lock:
            session = self._sessions.get(simulation_id)

        if session is not None:
            metrics = session.build_performance_metrics()
            return PerformanceMetricsResponse(**metrics)

        # Query database
        stmt = select(models.SimulationRun).where(models.SimulationRun.id == simulation_id)
        res = await db.execute(stmt)
        sim_run = res.scalar_one_or_none()
        if sim_run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Simulation with ID '{simulation_id}' not found.",
            )

        raw_metrics = sim_run.metrics or {}
        return PerformanceMetricsResponse(
            simulation_id=sim_run.id,
            initial_capital=sim_run.initial_capital,
            final_portfolio_value=sim_run.final_portfolio_value or sim_run.initial_capital,
            gross_pnl=raw_metrics.get("gross_pnl", 0.0),
            net_pnl=raw_metrics.get("net_pnl", 0.0),
            total_return_pct=sim_run.total_return_pct or 0.0,
            transaction_costs=raw_metrics.get("transaction_costs", 0.0),
            slippage_cost=raw_metrics.get("slippage_cost", 0.0),
            total_trades=raw_metrics.get("total_trades", 0),
            winning_trades=raw_metrics.get("winning_trades", 0),
            losing_trades=raw_metrics.get("losing_trades", 0),
            win_rate_pct=raw_metrics.get("win_rate_pct", 0.0),
            average_win=raw_metrics.get("average_win", 0.0),
            average_loss=raw_metrics.get("average_loss", 0.0),
            profit_factor=raw_metrics.get("profit_factor", 0.0),
            max_drawdown_pct=raw_metrics.get("max_drawdown_pct", 0.0),
            exposure_pct=raw_metrics.get("exposure_pct", 0.0),
            open_positions_count=raw_metrics.get("open_positions_count", 0),
        )

    async def get_simulation_decisions(
        self,
        simulation_id: str,
        db: AsyncSession,
    ) -> List[DecisionResponse]:
        """Get strategy decisions recorded for the simulation."""
        async with self._lock:
            session = self._sessions.get(simulation_id)

        if session is not None:
            return [DecisionResponse(**d) for d in session.decisions]

        # Query database
        stmt = select(models.SimulationRun).where(models.SimulationRun.id == simulation_id)
        res = await db.execute(stmt)
        sim_run = res.scalar_one_or_none()
        if sim_run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Simulation with ID '{simulation_id}' not found.",
            )

        raw_metrics = sim_run.metrics or {}
        stored_decs = raw_metrics.get("decisions", [])
        return [DecisionResponse(**d) for d in stored_decs]

    async def _get_active_session(
        self,
        simulation_id: str,
        db: AsyncSession,
    ) -> SimulationSession:
        """Lookup active session or raise appropriate 404 / 400."""
        async with self._lock:
            session = self._sessions.get(simulation_id)

        if session is not None:
            return session

        # Check DB to see if simulation exists in terminal state
        stmt = select(models.SimulationRun).where(models.SimulationRun.id == simulation_id)
        res = await db.execute(stmt)
        sim_run = res.scalar_one_or_none()
        if sim_run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Simulation with ID '{simulation_id}' not found.",
            )

        if sim_run.status in (
            models.SimulationStatus.STOPPED,
            models.SimulationStatus.COMPLETED,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot control simulation in terminal state {sim_run.status.value}.",
            )

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation '{simulation_id}' has no active in-memory session.",
        )

    def _attach_background_completion_handler(self, session: SimulationSession) -> None:
        """Attach a race-safe completion listener to the background clock task."""
        task = session.clock._task
        if task is not None and not task.done():

            def _on_done(_t: asyncio.Task[None]) -> None:
                # Schedule safe background sync without overwriting newer states
                asyncio.create_task(self._safe_on_task_complete(session))

            task.add_done_callback(_on_done)

    async def _safe_on_task_complete(self, session: SimulationSession) -> None:
        """Safely handle background task termination respecting authoritative clock state."""
        try:
            # Only sync as COMPLETED if clock actually transitioned to COMPLETED
            if session.clock.state == SimulationLifecycleState.COMPLETED:
                await session.sync_to_db(is_final=True)
                self._dispatch_complete_event(session, status="COMPLETED")
        except Exception:
            logger.exception("Error in _safe_on_task_complete for %s", session.simulation_id)

    def _build_simulation_response(
        self,
        session: SimulationSession,
        sim_run: Optional[models.SimulationRun] = None,
    ) -> SimulationResponse:
        """Construct typed SimulationResponse from active session."""
        clock_status = session.clock.get_status()
        port_state = session.portfolio.get_state()
        metrics = session.build_performance_metrics(port_state)

        return SimulationResponse(
            id=session.simulation_id,
            instrument_id=session.instrument_id,
            symbol=session.symbol,
            timeframe=session.timeframe,
            start_date=session.start_date,
            end_date=session.end_date,
            initial_capital=session.initial_capital,
            final_portfolio_value=port_state.total_portfolio_value,
            total_return_pct=port_state.total_return_pct,
            status=clock_status.state.value,
            is_baseline=session.is_baseline,
            speed=clock_status.speed,
            current_time=clock_status.current_time,
            step_index=clock_status.step_index,
            total_candles=clock_status.total_candles,
            progress_pct=clock_status.progress_pct,
            metrics=metrics,
            created_at=session.created_at,
            updated_at=datetime.now(timezone.utc),
        )

    def _dispatch_step_events(
        self,
        session: SimulationSession,
        step_res: ReplayStepResult,
    ) -> None:
        """Broadcast real-time simulation step events to WebSocket subscribers."""
        try:
            from app.websocket.manager import get_connection_manager
            from app.websocket.schemas import SimulationEventType

            manager = get_connection_manager()
            if manager.get_active_count(session.simulation_id) == 0:
                return

            sim_id = session.simulation_id
            v_time = step_res.timestamp.isoformat() if step_res.timestamp else None

            # 1. candle_update
            c = step_res.candle
            candle_evt = manager.create_event(
                simulation_id=sim_id,
                event_type=SimulationEventType.CANDLE_UPDATE,
                virtual_timestamp=v_time,
                payload={
                    "step_index": step_res.step_index,
                    "candle": {
                        "timestamp": c.timestamp.isoformat(),
                        "open": float(c.open),
                        "high": float(c.high),
                        "low": float(c.low),
                        "close": float(c.close),
                        "volume": float(c.volume),
                    },
                },
            )
            step_events = [candle_evt]

            # 2. order_executed (strategy or auto-exit fills)
            all_executions = list(step_res.strategy_orders_executed) + list(
                step_res.auto_exits_executed
            )
            for exec_res in all_executions:
                exec_evt = manager.create_event(
                    simulation_id=sim_id,
                    event_type=SimulationEventType.ORDER_EXECUTED,
                    virtual_timestamp=v_time,
                    payload={
                        "order_id": exec_res.order_id,
                        "trade_id": getattr(exec_res, "trade_id", None),
                        "side": (
                            exec_res.side.value
                            if hasattr(exec_res.side, "value")
                            else str(exec_res.side)
                        ),
                        "quantity": exec_res.quantity,
                        "execution_price": float(exec_res.execution_price or 0.0),
                        "market_price": float(exec_res.market_price or 0.0),
                        "slippage_cost": float(exec_res.slippage_cost or 0.0),
                        "transaction_cost": float(exec_res.transaction_cost or 0.0),
                        "status": (
                            exec_res.status.value
                            if hasattr(exec_res.status, "value")
                            else str(exec_res.status)
                        ),
                        "rejection_reason": exec_res.rejection_reason,
                        "is_auto_exit": exec_res in step_res.auto_exits_executed,
                    },
                )
                step_events.append(exec_evt)

            # 3. risk_check (queued orders)
            all_queued = list(step_res.strategy_orders_queued) + list(step_res.auto_exits_queued)
            for q_order in all_queued:
                risk_evt = manager.create_event(
                    simulation_id=sim_id,
                    event_type=SimulationEventType.RISK_CHECK,
                    virtual_timestamp=v_time,
                    payload={
                        "order_id": q_order.order_id,
                        "passed": True,
                        "reason": q_order.reason or "Order staged and approved by risk engine",
                        "side": (
                            q_order.side.value
                            if hasattr(q_order.side, "value")
                            else str(q_order.side)
                        ),
                        "quantity": q_order.quantity,
                    },
                )
                step_events.append(risk_evt)

            # 4. agent_decision (if a decision was recorded on this step)
            if session.decisions:
                latest_dec = session.decisions[-1]
                dec_evt = manager.create_event(
                    simulation_id=sim_id,
                    event_type=SimulationEventType.AGENT_DECISION,
                    virtual_timestamp=v_time,
                    payload={
                        "action": latest_dec.get("action", "HOLD"),
                        "confidence": float(latest_dec.get("confidence", 1.0)),
                        "quantity": latest_dec.get("quantity"),
                        "stop_loss": latest_dec.get("stop_loss"),
                        "take_profit": latest_dec.get("take_profit"),
                        "reason": latest_dec.get("reason", ""),
                        "market_regime": latest_dec.get("market_regime"),
                    },
                )
                step_events.append(dec_evt)

            # 5. position_updated & portfolio_updated
            st = step_res.portfolio_state or session.portfolio.get_state()
            pos_evt = manager.create_event(
                simulation_id=sim_id,
                event_type=SimulationEventType.POSITION_UPDATED,
                virtual_timestamp=v_time,
                payload={
                    "positions": [
                        {
                            "symbol": pos.symbol,
                            "quantity": pos.quantity,
                            "average_entry_price": float(pos.average_entry_price),
                            "current_price": float(pos.current_price),
                            "unrealized_pnl": float(pos.unrealized_gross_pnl),
                            "stop_loss": (
                                float(pos.stop_loss) if pos.stop_loss is not None else None
                            ),
                            "take_profit": (
                                float(pos.take_profit) if pos.take_profit is not None else None
                            ),
                            "is_open": pos.is_open,
                        }
                        for pos in st.positions.values()
                    ]
                },
            )
            step_events.append(pos_evt)

            port_evt = manager.create_event(
                simulation_id=sim_id,
                event_type=SimulationEventType.PORTFOLIO_UPDATED,
                virtual_timestamp=v_time,
                payload={
                    "cash": float(st.cash),
                    "portfolio_value": float(st.total_portfolio_value),
                    "gross_pnl": float(st.gross_pnl),
                    "net_pnl": float(st.net_pnl),
                    "total_return_pct": float(st.total_return_pct),
                    "exposure_pct": float(st.exposure_pct),
                    "open_positions_count": st.open_positions_count,
                },
            )
            step_events.append(port_evt)

            # Broadcast all events of this step sequentially under per-simulation lock
            asyncio.create_task(manager.broadcast_events(sim_id, step_events))

        except Exception:
            logger.exception(
                "Error broadcasting step events for simulation %s",
                session.simulation_id,
            )

    def _dispatch_complete_event(
        self,
        session: SimulationSession,
        status: str = "COMPLETED",
    ) -> None:
        """Broadcast simulation completion event to WebSocket subscribers."""
        try:
            from app.websocket.manager import get_connection_manager
            from app.websocket.schemas import SimulationEventType

            manager = get_connection_manager()
            if manager.get_active_count(session.simulation_id) == 0:
                return

            v_time = session.clock.current_time.isoformat() if session.clock.current_time else None
            metrics = session.build_performance_metrics()
            comp_evt = manager.create_event(
                simulation_id=session.simulation_id,
                event_type=SimulationEventType.SIMULATION_COMPLETE,
                virtual_timestamp=v_time,
                payload={
                    "status": status,
                    "total_steps": session.clock.step_index,
                    "final_portfolio_value": float(session.portfolio.total_portfolio_value),
                    "total_return_pct": float(session.portfolio.total_return_pct),
                    "metrics": metrics,
                },
            )
            asyncio.create_task(manager.broadcast(session.simulation_id, comp_evt))
        except Exception:
            logger.exception(
                "Error broadcasting completion event for simulation %s",
                session.simulation_id,
            )


_service_instance: Optional[SimulationService] = None


def get_simulation_service() -> SimulationService:
    """FastAPI dependency providing the singleton SimulationService."""
    global _service_instance
    if _service_instance is None:
        _service_instance = SimulationService()
    return _service_instance
