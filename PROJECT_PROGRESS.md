# Project Progress — NSE AI Trading Agent & Simulator

## Project Metadata
- **Project Name:** NSE AI Trading Agent & Simulator
- **Specification Source:** `PROJECT_SPECIFICATION.md`
- **Architecture:** Monorepo (Next.js Frontend + FastAPI Backend + PostgreSQL + Redis + Gemini Agent)
- **Status:** Phase 7B Complete (306/306 backend tests passing); Ready for Phase 7C Implementation

---

## Current Phase
**PHASE 7 — Agent Tool Layer**

## Sub-Phase Status
- [x] **PHASE 0: Repository & Architecture Scaffolding**
  - [x] 0A: Monorepo layout & base config (`.gitignore`, `.env.example`, `docker-compose.yml`, `README.md`)
  - [x] 0B: Backend scaffolding (`apps/api`, `pyproject.toml`, FastAPI skeleton, Ruff/Pyright setup, health endpoint)
  - [x] 0C: Frontend scaffolding (`apps/web`, Next.js 14, TypeScript, Tailwind CSS, quantitative financial terminal layout)
- [x] **PHASE 1: Backend & Database Foundation**
  - [x] 1A: PostgreSQL + SQLAlchemy 2.x + Alembic Foundation
  - [x] 1B: Core relational models (`instruments`, `candles`, `market_data_ranges`, `agents`, `simulations`, `orders`, `trades`, `positions`, `decisions`)
  - [x] 1C: Schema migrations generation & validation
  - [x] 1D: Database health & CRUD integration verification
- [x] **PHASE 2: Market Data Layer & OpenChart Isolation**
  - [x] 2A: `MarketDataProvider` abstract base class & schema
  - [x] 2B: OpenChart isolation POC & `NSEPublicProvider` adapter
  - [x] 2C: OHLCV data validation & integrity checks
  - [x] 2D: PostgreSQL persistence, missing range detection, and update tracking
  - [x] 2E: Data layer unit & integration tests
- [x] **PHASE 3: Market Data API & Candlestick Visualization**
  - [x] 3A: FastAPI REST endpoints for instruments & historical OHLCV data
  - [x] 3B: Lightweight Charts frontend integration with timeframe selector
  - [x] 3C: End-to-end historical fetch & chart display verification (RELIANCE 15m)
- [x] **PHASE 4: Quantitative Engine & Technical Indicators**
  - [x] 4A: Deterministic indicator calculation (EMA9, EMA20, SMA50, RSI14, MACD, ATR14, ATRP14)
  - [x] 4B: Deterministic descriptive market regime classification (Trend: BULLISH/BEARISH/SIDEWAYS via 3-of-4 indicator voting; Volatility: HIGH/NORMAL/LOW via previous 100 VALID ATRP14 observations strictly before candle t, None during warmup)
  - [x] 4C: Indicator API & calculation unit tests
  - [x] 4D: Chart indicator overlay & regime visualization
- [x] **PHASE 5: Trading, Portfolio & Risk Engine**
  - [x] 5A: Portfolio accounting & position tracking (Cash, P&L, exposure)
  - [x] 5B: Execution model (Next candle open, transaction costs, 0.05% slippage)
  - [x] 5C: Deterministic Risk Engine (Max risk/trade, max position, daily loss limits)
  - [x] 5D: Deterministic Stop-Loss & Take-Profit auto-triggers
  - [x] 5E: Trading & risk unit test suite
- [x] **PHASE 6: Historical Simulation Engine & Baseline Strategy**
  - [x] 6A: Chronological replay engine with strict no-look-ahead enforcement
  - [x] 6B: Simulation clock & playback controls (Start, Pause, Resume, Step, Speed)
  - [x] 6C: Deterministic benchmark baseline strategy (EMA 9/20 crossover + 2% SL)
  - [x] 6D: Simulation REST API & database persistence
  - [x] 6E: Backtest reproducibility verification
- [x] **PHASE 7: Agent Tool Layer**
  - [x] 7A: Pydantic schemas for typed agent tools & structured output
  - [x] 7B: 9 core agent tools implementation
  - [x] 7C: Safe tool execution harness (Risk engine routing, no arbitrary SQL/exec)
  - [x] 7D: Tool unit tests & schema validation
- [x] **PHASE 8: Gemini Reasoning Agent Integration**
  - [x] 8A: `google-genai` integration with Function Calling & Structured Outputs
  - [x] 8B: Agent mandate creation from natural language strategy prompt
  - [x] 8C: Event-driven decision cycle (Triggered on candle complete / key state changes)
  - [x] 8D: Compact bounded agent memory (Last 5 decisions, 10 trades)
  - [x] 8E: Agent failure handling & auto-pause
  - [x] 8F: Mocked & live decision cycle tests
- [x] **PHASE 9: Agent Configuration & Review UI**
  - [x] 9A: Agent creation modal/form (Strategy prompt, capital, risk parameters)
  - [x] 9B: Mandate review screen with edit & confirmation flow
  - [x] 9C: Agent management API endpoints
- [ ] **PHASE 10: Complete Trading Dashboard & WebSockets**
  - [x] 10A: WebSocket real-time event streaming server & client hook
  - [x] 10B: Quantitative trading terminal layout (Chart + Indicators + Trade Markers)
  - [ ] 10C: Agent Live Panel (Regime, Signal, Confidence, Observations, Live SL/TP)
  - [ ] 10D: Activity feed, Trade Log, and Performance panel
  - [ ] 10E: Interactive simulation controls bar
- [ ] **PHASE 11: Performance Evaluation & Comparison**
  - [ ] 11A: Comprehensive metrics (Net Return, Win Rate, Profit Factor, Max Drawdown)
  - [ ] 11B: Gemini token & latency tracker
  - [ ] 11C: AI Agent vs Baseline comparison view
- [ ] **PHASE 12: Testing, Hardening & Security Audit**
  - [ ] 12A: Full test suite execution (Pytest + Vitest)
  - [ ] 12B: Edge case testing (Gap openings, zero liquidity, Gemini failures)
  - [ ] 12C: Security verification (No arbitrary code execution, sanitized inputs)
- [ ] **PHASE 13: Containerization & Final Polish**
  - [ ] 13A: Production-ready Docker Compose configuration
  - [ ] 13B: Instrument seeding script
  - [ ] 13C: Architecture documentation & comprehensive README

---

## Completed in this Session (Phase 5B: Deterministic Execution Model & Accounting Reconciliation)
- **Execution Engine (`apps/api/app/trading/`):**
  - **Schemas (`schemas.py`):** Added typed models for `OrderRequest`, `ExecutionConfig`, and `ExecutionResult`. Reconciled `net_pnl` field descriptions.
  - **Execution Engine (`execution.py`):**
    - Enforced strict next candle OPEN execution ($P_{t+1, open}$), completely eliminating look-ahead bias and decision-candle close fills.
    - Directional slippage calculation (Default $0.05\% = 0.0005$):
      - BUY: $\text{market\_price} \times (1 + \text{slippage\_pct})$ (higher fill price for buyer)
      - SELL: $\text{market\_price} \times (1 - \text{slippage\_pct})$ (lower fill price for seller)
    - Deterministic transaction costs ($\text{nominal} \times \text{brokerage\_rate} + \text{fixed\_fee}$) and slippage cost impact calculation.
    - Graceful rejection when next candle is unavailable (end of series) or chronological sequence violated ($t_{\text{next}} \le t_{\text{decision}}$).
  - **Slippage Accounting Correction (`portfolio.py`):**
    - Resolved critical double-counting defect where `PortfolioTracker` received slippage-adjusted `execution_price` AND separately deducted `slippage_cost` from cash and P&L.
    - BUY cash outflow: $(\text{quantity} \times \text{execution\_price}) + \text{transaction\_cost}$.
    - SELL cash inflow: $(\text{quantity} \times \text{execution\_price}) - \text{transaction\_cost}$.
    - `total_net_pnl`: $\text{total\_gross\_pnl} - \text{total\_transaction\_costs}$.
    - Cumulative `total_slippage_cost` and per-order/trade `slippage_cost` preserved strictly as transparent informational metrics for reporting without double deduction.
    - Reconciled authoritative conservation invariant: $\text{Equity} = \text{Cash} + \text{Market Value} = \text{Initial Capital} + \text{Net P\&L}$ to the penny.
- **Targeted Unit & Regression Tests (`apps/api/tests/test_execution.py`, `test_portfolio.py`, `test_risk.py`):**
  - Added 4 dedicated regression tests preventing reintroduction of double-counting on BUY, SELL, full BUY->SELL round trip, and zero-slippage comparative baseline.
  - Added 15 comprehensive unit & regression tests for Phase 5C Risk Engine covering order validity, available cash sufficiency, SL/TP validation, max risk/trade (2%), max position exposure (25%), scaling prevention, max portfolio exposure (100%), max daily loss (5%), position sizing, fixed-fee regression, and end-to-end integration.
  - Total backend tests: 160/160 passing.

## Completed in this Session (Phase 5C: Deterministic Risk Engine)
- **Deterministic Risk Engine (`apps/api/app/trading/`):**
  - **Schemas (`schemas.py`):** Added `RiskConfig` (default 2% max risk/trade, 25% max position exposure, 100% max portfolio exposure, 5% max daily loss) and `RiskCheckResult`.
  - **Risk Engine (`risk.py`):**
    - Implemented `RiskEngine` with strict deterministic evaluation pipeline:
      1. Order validity (symbol non-empty, quantity > 0, price > 0).
      2. SELL order checks (requires active open position, requested quantity cannot exceed open quantity).
      3. Maximum daily loss limit (halts new BUY orders when intraday loss exceeds 5%; permits SELL orders).
      4. Available cash sufficiency (order cash requirement including estimated slippage and transaction fees <= available cash).
      5. Stop-loss & take-profit validity (SL > 0, SL < entry for BUY; TP > 0, TP > entry for BUY; SL < TP).
      6. Maximum risk per trade (enforces trade risk $\le 2\%$ of current portfolio equity).
      7. Maximum position exposure (enforces $(Q_{\text{existing}} + Q_{\text{new}}) \times P_{\text{exec}} \le 25\%$ of current equity, preventing scaling bypass).
      8. Maximum portfolio exposure (enforces aggregate market value across all open positions $\le 100\%$ of equity).
    - Implemented `calculate_position_size()` helper deterministically sizing orders bounded by capital, risk, position exposure, and available cash.
    - **Position Sizing Fixed Fee Correction:** Reconciled `calculate_position_size()` cash constraint to incorporate `fixed_fee_per_order`, ensuring `calculate_position_size()` and `validate_order()` share the exact same cash cost model and prevent returning quantities that fail subsequent cash validation.
  - **Clean Package Exports (`__init__.py`):** Exported `RiskEngine`, `RiskConfig`, and `RiskCheckResult`.
- **Targeted Regression Tests (`test_risk.py`):**
  - Added `test_calculate_position_size_fixed_fee_regression` proving: (1) returned quantity is affordable, (2) passes `validate_order()`, (3) one additional unit fails cash check, (4) returns 0 when cash $\le$ fixed fee.

## Completed in this Session (Phase 5D: Stop-Loss & Take-Profit Auto-Triggers)
- **Deterministic Auto-Triggers (`apps/api/app/trading/triggers.py`):**
  - Implemented `check_position_trigger`: Completed-candle OHLC extremes evaluation ($Low \le SL$, $High \ge TP$).
  - Implemented strict dual-touch resolution: `STOP_LOSS` takes strict precedence when a candle touches both SL and TP (conservative deterministic rule).
  - Implemented `create_exit_order`: Creates automatic market exit `OrderRequest` with `decision_price` as metadata only.
  - Implemented `TriggerMonitor`:
    - Enforces deterministic per-timestamp sequencing:
      1. Execute pending orders scheduled for current candle OPEN ($P_{t, open}$).
      2. Update portfolio state from executions in `PortfolioTracker`.
      3. Process newly completed candle $t$'s SL/TP trigger conditions against remaining active positions.
      4. Queue newly generated automatic exit orders for next available candle OPEN ($t+1$).
    - Enforces pending-exit deduplication: In-flight queued exit orders prevent duplicate exit emission.
    - Enforces closed-position terminal state: Once closed, no further triggers can be generated for that position.
    - Preserves Phase 5B execution model (directional slippage, fees) and Phase 5A accounting (no double-counted slippage).
  - Clean package exports in `apps/api/app/trading/__init__.py`.
  - **Phase 5D Audit Fix (Cross-Symbol Isolation):**
    - Updated `TriggerMonitor.execute_pending_exits()` to accept `symbol: Optional[str] = None` and pop/execute only matching exits, leaving other symbols' exits pending.
    - Updated `TriggerMonitor.process_simulation_cycle()` to resolve the target symbol and pass it to both `execute_pending_exits()` and `evaluate_completed_candle()`.
    - Updated `TriggerMonitor.evaluate_completed_candle()` to safely infer symbol for single-position portfolios, while raising a `ValueError` on multi-position portfolios if `symbol` is omitted, preventing cross-symbol price contamination.
- **Targeted Unit & Integration Tests (`apps/api/tests/test_triggers.py`):**
  - Added 15 comprehensive tests (11 core + 4 audit regression tests) covering exact boundary touches, SL vs TP discrimination, dual-touch precedence, trigger candle vs execution candle separation, slippage/fee reconciliation, deduplication, terminal state, final candle handling, multi-position triggers, cross-symbol execution isolation, independent candle execution, multi-position symbol omission guard, and single-symbol inference.
  - Total backend tests: 175/175 passing.

## Completed in this Session (Phase 5E: Trading & Risk Unit Test Suite)
- **Coverage Audit & Internal Map Across All 12 Core Requirements:**
  - Audited existing test coverage across Portfolio, Execution, Risk, Triggers, and integration tests.
  - Verified non-duplication: avoided duplicating already well-tested behaviors.
- **Strengthened Existing Tests:**
  - `test_portfolio.py::test_mark_to_market_updates`: Strengthened to verify active unrealized net P&L conservation (`net_pnl == unrealized_gross_pnl - total_transaction_costs`) and exact equity conservation (`total_portfolio_value == initial_capital + net_pnl`).
  - `test_portfolio.py::test_partial_position_exit_realized_pnl`: Strengthened to verify post-partial-exit cash conservation and equity invariants.
  - `test_risk.py::test_max_daily_loss_limit_halts_buy_orders_but_permits_sells`: Strengthened with post-liquidation verification proving that converting an unrealized daily loss into realized cash loss preserves the daily loss breach and continues halting new BUY orders.
- **Cross-Component Trading Flows & Adversarial Suite (`apps/api/tests/test_trading_flows.py`):**
  - Added `test_full_lifecycle_risk_execution_autotrigger_portfolio_flow`: Full unified round-trip pipeline across Phase 5C Sizing & Risk Check $\to$ Phase 5B Buy Fill $\to$ Phase 5A Portfolio Tracking $\to$ Phase 5D Take-Profit Auto-Trigger $\to$ Phase 5B Sell Fill $\to$ Phase 5A Full Reconciliation (invariants hold to the penny, zero double-counted slippage/fees).
  - Added `test_partial_manual_exit_followed_by_autotrigger_on_remaining_quantity`: Proves auto-trigger correctly sizes exit order to remaining open shares (not initial quantity) after a partial manual exit.
  - Added `test_rejected_orders_produce_zero_side_effects_on_state`: Proves rejections across RiskEngine, ExecutionEngine, and TriggerMonitor produce zero side-effects on cash, positions, or trade records.
  - Added `test_multi_position_portfolio_interleaved_lifecycle_accounting`: Proves concurrent multi-position lifecycle with independent SL and TP executions and accurate cumulative portfolio win rate (50%).
- **Total Backend Test Count:** 179/179 passing in 4.72s.

## Completed in this Session (Phase 6A: Chronological Replay Engine)
- **Chronological Replay Engine (`apps/api/app/trading/simulation/replay.py`):**
  - Implemented `ChronologicalReplayEngine` coordinating market data playback, order executions, portfolio accounting, stop-loss / take-profit auto-triggers, and strategy decision lifecycles.
  - Enforced exact 6-step per-candle simulation sequence:
    1) Execute pending automatic SL/TP exits at current candle OPEN.
    2) Execute pending strategy orders at current candle OPEN.
    3) Update authoritative `PortfolioTracker`.
    4) Complete current candle and mark active positions to market at CLOSE.
    5) Evaluate completed-candle SL/TP triggers and queue exits for $t+1$ OPEN.
    6) Evaluate strategy signals using data strictly through completed candle $t$ and queue orders for $t+1$ OPEN.
  - **Same-Symbol Precedence Rule:** Implemented strict auto-exit precedence over strategy orders on the same symbol at Open, preventing strategy orders from reopening/scaling a position being simultaneously liquidated. Conflicting strategy orders are rejected with `OrderStatus.REJECTED` without side effects on cash or portfolio. Verified cross-symbol isolation (exit on symbol A does not block symbol B).
  - **Strict No-Look-Ahead:** Strategies receive `ReplayContext` with `visible_candles` containing only completed candles $\le t$. Future candles are completely inaccessible. Decisions made on candle $t$ execute strictly at $t+1$ Open; never at $t$ Close.
  - **Virtual Simulation Clock:** Clock advances strictly via historical candle timestamps ($T_0, T_1, \dots$). `datetime.now()` is completely prohibited in replay and accounting.
  - **Idempotency & Repeated Timestamp Guard:** Re-processing an already-processed candle raises `DuplicateTimestampError` and preserves exact state without modification. Out-of-order candles raise `OutOfOrderCandleError`.
  - **End-of-Series Behavior:** Orders queued at the final candle $T_{\text{final}}$ are cleanly rejected because no next candle exists. Open positions remain open, marked to market at final candle Close (never artificially liquidated).
  - **Database Historical Loader:** Implemented `load_historical_candles_from_db` and `ChronologicalReplayEngine.from_db` querying locked historical candles from PostgreSQL strictly with `ORDER BY timestamp ASC` without external network/API fetches.
  - **Component Isolation:** Each engine instance owns isolated instances of `PortfolioTracker`, `ExecutionEngine`, `RiskEngine`, and `TriggerMonitor`.
- **Targeted Unit & Integration Tests (`apps/api/tests/test_replay.py`):**
  - Added 17 comprehensive unit and integration tests covering dataset validation, strict ascending timestamps, virtual clock advancement, no-look-ahead visible candles, next-candle execution timing, exact 6-step sequence, same-symbol precedence, cross-symbol isolation, idempotency, end-of-series clean rejection, deterministic reproducibility, manual order queueing, and database loader integration.
  - **Total Backend Test Count:** 196/196 passing in 4.88s.

## Completed in this Session (Phase 6B: Simulation Clock & Playback Controls)
- **Simulation Clock & Controller (`apps/api/app/trading/simulation/clock.py`):**
  - Implemented `SimulationClock` managing asynchronous playback execution, lifecycle state transitions, wall-clock pacing regulation, and single-step advancing on top of `ChronologicalReplayEngine`.
  - **Frozen Lifecycle State Machine:**
    - `CREATED` $\to$ `RUNNING` (via `start()`)
    - `RUNNING` $\to$ `PAUSED` (via `pause()`)
    - `PAUSED` $\to$ `RUNNING` (via `resume()`)
    - `RUNNING` or `PAUSED` $\to$ `STOPPED` (via `stop()`, strictly terminal)
    - `RUNNING` $\to$ `COMPLETED` (automatically upon series exhaustion, strictly terminal)
  - **Idempotency & Guard Invariants:**
    - `start()` on `RUNNING`: idempotent no-op.
    - `resume()` on `RUNNING`: idempotent no-op.
    - `pause()` on `PAUSED`: idempotent no-op.
    - `stop()` on `STOPPED`: idempotent no-op.
    - `start()` or `resume()` on `STOPPED` / `COMPLETED`: strictly rejected with `InvalidStateTransitionError`.
    - `pause()` on `CREATED` / `STOPPED` / `COMPLETED`: strictly rejected with `InvalidStateTransitionError`.
    - `step()` strictly valid only while `PAUSED`; advances exactly 1 completed candle cycle and freezes in `PAUSED` (or transitions to `COMPLETED` if final candle reached).
  - **Async Execution & Concurrency Safety:**
    - Single managed background `asyncio.Task` for continuous playback; duplicate tasks prevented via `_control_lock`.
    - Step processing serialized via `_step_lock`, preventing race conditions during concurrent control calls.
  - **Pacing Independence & Speeds:**
    - Supported multipliers: `0.5x`, `1.0x`, `2.0x`, `5.0x`, `10.0x`.
    - Speed multiplier regulates only wall-clock `asyncio.sleep` delay; simulation timestamps, execution prices, and trading results remain bit-for-bit identical regardless of speed or execution mode (continuous vs stepped).
  - **Clean Package Exports (`apps/api/app/trading/simulation/__init__.py`, `apps/api/app/trading/__init__.py`):**
    - Exported `SimulationClock`, `SimulationLifecycleState`, `SimulationClockStatus`, `SimulationClockError`, `InvalidStateTransitionError`, `VALID_PLAYBACK_SPEEDS`, and `StepCallback`.
- **Targeted Unit & Integration Tests (`apps/api/tests/test_clock.py`):**
  - Added 21 comprehensive tests covering initial state, status snapshot, full lifecycle transitions, terminal state rejections, idempotent controls, STEP invariants, continuous playback, task cleanup, duplicate task prevention, pause halting, resume continuity, speed validation, pacing regulation, bit-for-bit continuous vs stepped equivalence, speed equivalence (0.5x-10x), virtual clock authority, control interleaving, empty dataset handling, final-candle completion, and reset behavior.
  - **Total Backend Test Count:** 217/217 passing in 5.58s.

## Completed in this Session (Phase 6C: Deterministic Benchmark Baseline Strategy)
- **Benchmark Baseline Strategy (`apps/api/app/trading/strategy/baseline.py`):**
  - Implemented `BenchmarkBaselineStrategy` as a pure, decoupled strategy component conforming to `StrategyCallable = Callable[[ReplayContext], Sequence[OrderRequest]]`.
  - **Frozen Baseline Rules:**
    - SPOT, LONG-ONLY, SINGLE-POSITION strategy.
    - Bullish crossover: $\text{EMA9}[t-1] \le \text{EMA20}[t-1]$ AND $\text{EMA9}[t] > \text{EMA20}[t]$.
    - Bearish crossover: $\text{EMA9}[t-1] \ge \text{EMA20}[t-1]$ AND $\text{EMA9}[t] < \text{EMA20}[t]$.
    - Equality: $\text{EMA9}[t] == \text{EMA20}[t]$ emits `HOLD`.
    - Warmup rule: Any missing values emit `HOLD` (bars $0 \dots 19$ emit `HOLD`; earliest valid signal at bar 20 / 21st candle).
    - If FLAT: bullish crossover $\to$ BUY; bearish crossover $\to$ HOLD (never short sells).
    - If ALREADY LONG: bullish crossover $\to$ HOLD (never scales into existing position); bearish crossover $\to$ SELL to close the entire position.
  - **Exact Stop-Loss Reference:**
    - BUY orders calculate exact 2% stop-loss from decision candle $t$ Close: $\text{round}(P_{t, \text{close}} \times 0.98, 2)$.
    - Never calculated from $t+1$ Open or execution fill price.
  - **RiskEngine Integration & Sizing:**
    - Sized via `RiskEngine.calculate_position_size()`, respecting cash, 2% risk limit, and 25% max position exposure limit.
    - If cash is insufficient, emits `HOLD`.
  - **Zero Market-Regime Dependency:**
    - Zero imports or references to `app.indicators.regime`, `TrendRegime`, or `VolatilityRegime`. Signal depends solely on EMA9 and EMA20.
  - **Deterministic Order ID Generation:**
    - Generates deterministic order IDs based on side, symbol, and virtual timestamp, ensuring identical inputs produce bit-for-bit identical `OrderRequest` objects.
  - **Clean Package Exports (`apps/api/app/trading/strategy/__init__.py`, `apps/api/app/trading/__init__.py`):**
    - Exported `BenchmarkBaselineStrategy`, `SIGNAL_BUY`, `SIGNAL_SELL`, and `SIGNAL_HOLD`.
- **Targeted Unit & Integration Tests (`apps/api/tests/test_baseline.py`):**
  - Added 18 comprehensive tests covering exact bullish/bearish crossover boundaries, equality at current candle, missing EMA values, warmup period (bars 0..19), flat vs long position rules, shorting/scaling prevention, exact stop-loss calculation, stop-loss reference price preservation, RiskEngine sizing and cash gating, next-candle Open execution, zero regime dependency AST check, deterministic output reproducibility, and full integration with `ChronologicalReplayEngine` and `SimulationClock`.
  - **Total Backend Test Count:** 235/235 passing in 5.65s.

## Completed in this Session (Phase 6D: Simulation REST API & Database Persistence)
- **Database Models (`apps/api/app/database/models/trading.py`):**
  - Added `STOPPED = "STOPPED"` to `SimulationStatus` enum without altering existing values (`CREATED`, `RUNNING`, `PAUSED`, `COMPLETED`, `FAILED`).
- **REST API Schemas (`apps/api/app/trading/simulation/schemas.py`):**
  - Implemented typed Pydantic models:
    - `SimulationCreateRequest`: strictly validated symbol, timeframe, date boundaries, initial capital, speed, execution and risk configs.
    - `SimulationResponse`: comprehensive session state including virtual timestamp, step index, progress, speed, status, and metrics.
    - `TradeResponse`: executed trade records.
    - `PerformanceMetricsResponse`: full performance summary matching Section 58 of specification (win rate, profit factor, max drawdown, exposure).
    - `DecisionResponse`: chronological strategy decision events.
- **Service & Session Layer (`apps/api/app/trading/simulation/service.py`):**
  - `SimulationSession`:
    - Manages isolated component instances per simulation ID (`PortfolioTracker`, `RiskEngine`, `ExecutionEngine`, `TriggerMonitor`, `BenchmarkBaselineStrategy`, `ChronologicalReplayEngine`, `SimulationClock`).
    - Thread-safe idempotent database persistence via `sync_to_db` (orders, trades, snapshots, metrics).
    - Peak portfolio tracking and peak-to-trough maximum drawdown calculation.
    - Step decision recording (BUY/SELL/HOLD) without inventing Gemini decisions.
  - `SimulationService`:
    - Atomic creation with pre-validation of historical candles via `load_historical_candles_from_db`.
    - Lifecycle delegation: `start_simulation`, `pause_simulation`, `resume_simulation`, `step_simulation`, `stop_simulation` directly driving `SimulationClock`.
    - Race-safe background completion handler with deadlock-free synchronization.
    - Read query handlers: `get_simulation`, `get_simulation_trades`, `get_simulation_performance`, `get_simulation_decisions` with seamless fallback to PostgreSQL when sessions are evicted from memory.
- **REST Endpoints (`apps/api/app/api/v1/simulations.py`, `apps/api/app/api/v1/router.py`):**
  - Registered all 10 documented endpoints:
    - `POST /api/v1/simulations`
    - `GET  /api/v1/simulations/{id}`
    - `POST /api/v1/simulations/{id}/start`
    - `POST /api/v1/simulations/{id}/pause`
    - `POST /api/v1/simulations/{id}/resume`
    - `POST /api/v1/simulations/{id}/step`
    - `POST /api/v1/simulations/{id}/stop`
    - `GET  /api/v1/simulations/{id}/trades`
    - `GET  /api/v1/simulations/{id}/performance`
    - `GET  /api/v1/simulations/{id}/decisions`
  - Proper mapping of `InvalidStateTransitionError` to HTTP 400 Bad Request.
- **Targeted Unit & Integration Tests (`apps/api/tests/test_simulations_api.py`):**
  - Added 16 comprehensive tests covering:
    1. Simulation creation and validation.
    2. Validation errors (symbol, dates, timeframe, capital, speed).
    3. Creation atomicity (failed validation leaves no corrupted database rows).
    4. Simulation state retrieval and 404 handling.
    5. Full lifecycle transitions (`START` -> `PAUSE` -> `STEP` -> `RESUME` -> `STOP`).
    6. Lifecycle idempotency and invalid transition rejections.
    7. Concurrent start/resume calls without duplicate tasks.
    8. Idempotent database persistence (no duplicate orders/trades/snapshots on multiple syncs).
    9. Authoritative read endpoints (trades, performance, decisions).
    10. Complete multi-simulation isolation across two simulation IDs.
    11. Automatic end-of-series completion.
    12. Playback speed independence (0.5x vs 5.0x bit-for-bit results).
    13. Background completion race safety (never overwriting STOPPED state).
    14. Direct delegation to `SimulationClock` with zero duplicate loop.
    15. Terminal `STOPPED` state database persistence.
    16. Authoritative GET endpoints reading from PostgreSQL after session eviction from memory.
  - **Total Backend Test Count:** 251/251 passing in 10.11s.

## Completed in this Session (Phase 6E: Backtest Reproducibility Verification)
- **Dedicated Reproducibility Suite (`apps/api/tests/test_simulation_reproducibility.py`):**
  - Added 8 comprehensive reproducibility and adversarial test scenarios:
    1. `test_twin_simulation_bit_for_bit_identical_results`: Verified that two independent simulation runs over identical locked dataset produce 100% identical trades (quantities, prices, fees, slippage, PnL, exit reasons), executions, portfolio cash, equity, exposure, Section 58 performance metrics, max drawdown, and strategy decision logs.
    2. `test_playback_independence_continuous_stepped_pause_resume`: Verified that continuous playback, pure bar-by-bar `step()` execution while paused, and mixed pause/resume/step execution produce bit-for-bit identical trading and portfolio outcomes.
    3. `test_playback_speed_independence_all_five_speeds`: Verified that runs across all 5 supported playback speeds (0.5x, 1x, 2x, 5x, 10x) produce identical financial results, proving wall-clock delay does not alter simulation logic.
    4. `test_persistence_reproducibility_twin_db_runs`: Verified that two independent simulations persisted to PostgreSQL/SQLite produce identical database records (`simulation_runs`, `orders`, `trades`, `portfolio_snapshots`), and that repeated synchronization is strictly idempotent.
    5. `test_dataset_lock_and_no_lookahead_isolation`: Verified that appending newer future candles to the database after simulation initialization does not leak into the simulation.
    6. `test_same_symbol_auto_exit_precedence_reproducibility`: Verified that the auto-exit precedence rule deterministically rejects conflicting strategy orders for the same symbol at the same candle Open.
    7. `test_exact_warmup_and_boundary_crossover_determinism`: Verified discrete crossover detection boundaries (equality yielding HOLD, strict crossing yielding BUY/SELL, warmup bars 0..19 yielding HOLD).
    8. `test_adversarial_rapid_api_controls_determinism`: Verified that rapid concurrent `start()`, `pause()`, and `resume()` commands do not race or drift, producing outcomes identical to a reference stepped run.
- **Genuine Production Defect Resolved:**
  - **Issue:** Cross-simulation primary key collision on `orders.id` during database synchronization when multiple simulations executed on identical symbols and timestamps.
  - **Root Cause:** `SimulationSession.sync_to_db()` assigned `models.Order.id = exec_res.order_id`, which for baseline strategy was `BASELINE_BUY_{symbol}_{timestamp}`. Because `orders.id` is a global primary key, independent simulations collided on the unique constraint, causing sync rollbacks.
  - **Fix:** Assigned `models.Order.id` using `str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{self.simulation_id}_{exec_res.order_id}"))`, guaranteeing deterministic, simulation-scoped identities that are strictly idempotent within a session and unique across sessions.
- **Total Backend Test Count:** 259/259 passing in 10.99s across 23 test modules.

## Completed in this Session (Phase 7: Agent Tool Layer — 7A, 7B, 7C, 7D)
- **Phase 7A (Schemas Layer):**
  - Implemented 18 Pydantic v2 schemas in `app/trading/agent/schemas.py` with `extra="forbid"` and `frozen=True`.
  - Comprehensive schemas for input/output payloads across all 9 agent tools, standard execution envelope `ToolExecutionResult`, and the structured LLM decision contract `AgentDecision`.
- **Phase 7B (9 Core Agent Tools):**
  - Implemented 9 typed agent tools in `app/trading/agent/tools.py` operating over authoritative simulation state via `ToolExecutionContext` adapter without redundant state models:
    1. `get_market_data`: Historical window queries with lookback constraints.
    2. `get_indicators`: Multi-timeframe technical indicator calculations (EMA9, EMA20, SMA50, RSI14, MACD, ATR14).
    3. `get_market_regime`: Deterministic trend & volatility classification snapshot.
    4. `get_position`: Live position queries, PnL, and exposure.
    5. `get_portfolio`: Cash balance, equity, margin, daily PnL, and open positions.
    6. `get_trade_history`: Closed trade logs with pagination/filtering.
    7. `calculate_position_size`: Pre-trade risk-adjusted position sizing with exposure capping.
    8. `place_simulated_order`: Next-candle order staging subject to Section 39 risk verification and single-staged-order rule.
    9. `close_simulated_position`: Position closing order staging with single-staged-order rule.
- **Phase 7C (Safe Tool Execution Harness):**
  - Implemented `ToolRegistry` and `ToolExecutionHarness` in `app/trading/agent/harness.py`.
  - Serves as the strict trust boundary between untrusted agent input and deterministic simulation backend:
    - Whitelist tool dispatch (rejects unregistered tools).
    - Strict input validation against Pydantic schemas (rejects extra fields, wrong types, out-of-range bounds).
    - Authoritative context injection (agent cannot supply or tamper with `ToolExecutionContext`).
    - Standardized `ToolExecutionResult` envelope with structured error taxonomy (`ToolErrorType`).
    - Internal exception containment ensuring crashes in tool handlers never corrupt simulation state.
- **Phase 7D (Tool Unit Tests & Schema Validation):**
  - Split and completed comprehensive Phase 7 test coverage across 4 dedicated modules:
    1. `apps/api/tests/test_agent_schemas.py` (25 tests): Boundary validations, strict immutability, extra-field forbidding, serialization round-trips, and full `ToolErrorType` taxonomy.
    2. `apps/api/tests/test_agent_tools_readonly.py` (28 tests): Read-only tool purity, warmup transitions, lookback boundary limits, symbol mismatch handling, empty visible candles, and capital exhaustion.
    3. `apps/api/tests/test_agent_tools_trading.py` (13 tests): Order staging, risk engine rejections, SL/TP validation, single-staged-order rule per candle, retry semantics, and `ChronologicalReplayEngine` 3-step lifecycle.
    4. `apps/api/tests/test_tool_harness.py` (31 tests): Harness registration, dispatch, argument tampering prevention, context isolation, output schema enforcement, exception containment, and end-to-end replay integration workflow.
  - Phase 7 dedicated test count: **97 tests** (0 failures).
- **Total Backend Test Count:** 356/356 passing in 11.56s across 29 test modules.

## Completed in this Session (Phase 8A: google-genai Integration with Function Calling & Structured Outputs)
- **Isolated Gemini Integration Package (`app/trading/agent/gemini`):**
  - Implemented `GeminiConfig` in `config.py`: application settings integration (`GEMINI_API_KEY`, `GEMINI_MODEL`), model parameters, and timeout configs.
  - Implemented typed domain envelopes in `schemas.py` (`GeminiRequest`, `GeminiResponse`, `GeminiToolCall`, `GeminiToolResponse`, `GeminiMessage`, `GeminiErrorType`): strictly prevents `google-genai` types from leaking into the core trading domain.
  - Implemented `build_gemini_tools` and `validate_gemini_tool_call` in `tools.py`: dynamically derives Gemini `FunctionDeclaration` objects directly from the frozen Phase 7 `ToolRegistry`, preserving tool names, descriptions, and Pydantic input schemas (`parameters_json_schema`).
  - Implemented `GeminiClient` in `client.py`: provides synchronous (`generate`) and asynchronous (`generate_async`) methods, handles tool calling candidates, validates tool calls against registry, parses structured `AgentDecision` outputs, strips markdown fences, captures token usage metadata, and contains SDK/network exceptions safely into categorized `GeminiResponse` envelopes.
- **Dedicated Phase 8A Test Suite (`apps/api/tests/test_gemini_integration.py`):**
  - Implemented 29 focused unit tests covering config defaults/settings, full 9-tool declaration translation, tool whitelisting and unauthorized tool rejection, model parameter forwarding, valid BUY/HOLD/SELL `AgentDecision` parsing, markdown fence stripping, out-of-range bounds / malformed JSON rejections, single and parallel function calls, unauthorized tool call rejection, empty/blocked candidate handling, genai `APIError`, `401/403` auth errors, `429` rate limit errors, async generation, multi-turn message history translation, and SDK isolation boundaries.
- **Total Backend Test Count:** 385/385 passing in 12.15s across 30 test modules.

## Current Task
Phase 8E (Agent Failure Handling & Auto-Pause) is complete, audited, and verified **SAFE TO FREEZE**. All 468 backend tests pass, linters/formatters are clean, and frontend compiles with 0 errors. Awaiting user instruction before proceeding to Phase 8F.

## Tests & Verification
- Backend Pytest (`apps/api/tests`): PASS (468/468 tests passed in 13.08s; 28 focused Phase 8E tests)
- Frontend Build (`apps/web`): PASS (`next build` succeeded, 0 errors)
- Ruff Lint & Format: PASS (0 errors, all 114 files formatted)

## Known Issues
- None

## Important Architectural Decisions
- **Source of Truth:** PostgreSQL is the source of truth for all historical market data, simulations, orders, and agent decisions.
- **Simulation Source of Truth:** `SimulationClock` + `ChronologicalReplayEngine` remain the sole authoritative source of truth for runtime simulation state, virtual clock progression, order execution, and portfolio accounting. The REST API delegates strictly to these components without creating a secondary simulation loop.
- **Trust Boundary:** `ToolExecutionHarness` is the strict trust boundary between untrusted Gemini tool calls and the simulation backend. Gemini never accesses database, files, or internal state directly.
- **Function Calling Derivation:** Gemini tool declarations are derived strictly and deterministically from the Phase 7 `ToolRegistry`. No secondary registry or manual schema duplication exists.
- **SDK Isolation Boundary:** `google-genai` SDK classes remain strictly contained inside `app.trading.agent.gemini`. The trading domain interacts exclusively through typed Pydantic models (`GeminiRequest`, `GeminiResponse`, `GeminiToolCall`, `AgentDecision`).
- **Single Staged Order per Candle:** An agent tool invocation may stage at most one order per candle step. Subsequent staging attempts within the same candle step are rejected with `ORDER_ALREADY_STAGED` without corrupting the previously staged order.
- **Sub-Phase Separation:** Phase 8A establishes only the communication and parsing layer for Gemini. Decision reconciliation, natural-language mandates (8B), event-driven agent loop (8C), memory (8D), auto-pause policy (8E), and live decision-cycle testing (8F) remain strictly partitioned.





