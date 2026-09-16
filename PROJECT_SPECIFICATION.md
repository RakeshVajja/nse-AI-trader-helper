# NSE AI Trading Agent & Simulator — Final Master Plan

## 1. Project Objective

Build a modern, full-stack **AI-powered simulated trading platform for NSE stocks and indices**.

The platform allows a user to:

1. Select an NSE stock or index.
2. Select a trading timeframe.
3. Set initial capital and risk constraints.
4. Describe a trading strategy in natural language.
5. Create a custom AI trading agent using Gemini.
6. Let the agent continuously participate in a historical market simulation.
7. Give the agent access to quantitative market-data and portfolio tools.
8. Allow Gemini to reason about market conditions and make **BUY / SELL / HOLD** decisions.
9. Enforce deterministic risk controls independently of Gemini.
10. Execute all trades in a simulated environment.
11. Display the agent's activity, decisions, positions, stop-loss, trades and performance.
12. Store downloaded market data locally in PostgreSQL so it can be reused in future simulations.

### Core concept

> **Gemini is the reasoning agent operating inside a deterministic quantitative trading and risk-management environment.**

It is **not** merely an NLP parser and **not** a stock-price prediction model.

---

# 2. Scope

## Supported instruments

Initially support:

### NSE equities

```text
RELIANCE
TCS
INFY
HDFCBANK
ICICIBANK
SBIN
ITC
```

### NSE indices

```text
NIFTY 50
BANK NIFTY
NIFTY IT
```

Design the instrument system so more NSE instruments can be added later.

Do NOT implement initially:

* Options
* Futures
* Commodities
* Crypto
* Forex
* International markets

---

# 3. Supported Timeframes

Initial timeframes:

```text
5m
15m
30m
1h
1d
```

Default:

```text
15m
```

---

# 4. User Flow

The complete flow should be:

```text
User
 ↓
Select Stock / Index
 ↓
Select Timeframe
 ↓
Set Initial Capital
 ↓
Set Risk Limits
 ↓
Describe Strategy
 ↓
Gemini creates Agent Configuration
 ↓
User reviews configuration
 ↓
User starts simulation
 ↓
Historical data is replayed chronologically
 ↓
Agent observes market state
 ↓
Agent uses tools when necessary
 ↓
Gemini reasons
 ↓
BUY / SELL / HOLD
 ↓
Deterministic Risk Engine
 ↓
Simulated Execution
 ↓
Portfolio State Updated
 ↓
Agent receives updated state on future events
 ↓
Simulation continues
 ↓
Performance / decisions / trades displayed
```

---

# 5. Gemini Must Be a Real Agent

Do **not** implement:

```text
Natural Language
       ↓
Gemini
       ↓
EMA9 > EMA20
       ↓
Fixed Strategy
```

and then stop using Gemini.

That would make Gemini only a strategy parser.

Instead:

```text
User Strategy
      ↓
Gemini Agent
      ↓
Observe
      ↓
Reason
      ↓
Use Tools
      ↓
Observe Tool Results
      ↓
Decide
      ↓
Risk Validation
      ↓
Simulated Execution
      ↓
Updated Environment
      ↓
Agent observes again
```

Gemini must participate throughout the simulation.

---

# 6. Agent Responsibilities

Gemini should be responsible for:

* understanding the user's trading objectives
* understanding the user's preferred strategy/style
* analyzing supplied market information
* interpreting technical indicators
* considering market regime
* considering current portfolio/position
* considering recent trades
* deciding whether a trade setup is favorable
* deciding BUY / SELL / HOLD
* deciding whether additional information is needed
* using available tools
* selecting position size within allowed constraints
* proposing stop-loss/take-profit
* explaining the decision concisely
* reassessing positions when market conditions materially change

Gemini must **not** directly modify the database or portfolio.

---

# 7. Deterministic Responsibilities

Python/backend must handle:

* market-data retrieval
* OHLCV storage
* EMA calculation
* RSI calculation
* MACD calculation
* SMA calculation
* market-regime calculation
* portfolio accounting
* P&L
* position sizing calculations
* transaction costs
* slippage
* stop-loss enforcement
* take-profit enforcement
* risk limits
* order validation
* order execution
* simulation time
* historical replay

This separation is mandatory.

---

# 8. Gemini API

Use the official:

```text
google-genai
```

Python SDK.

Use the current Gemini agent-oriented API/interface supported by the current SDK.

Use:

* Function Calling
* Structured Outputs
* Pydantic validation

Do not hardcode obsolete Gemini API patterns if the current SDK provides a newer recommended interface.

---

# 9. Token-Efficient Gemini Usage

Do **not** call Gemini on every tick.

Use event-driven decision cycles.

The system should monitor the market deterministically.

Possible triggers:

```text
new completed candle
significant price movement
EMA crossover/state change
RSI threshold crossing
MACD state change
market regime change
position nearing stop-loss
position nearing take-profit
new relevant context/news event
manual re-evaluation
```

For MVP, primarily trigger decisions on:

```text
new completed candle
+
important state changes
```

If nothing meaningful changed:

```text
DO NOT CALL GEMINI
```

---

# 10. Agent Lifecycle

Agent states:

```text
CREATED
READY
RUNNING
ANALYZING
WAITING
PAUSED
ERROR
COMPLETED
```

Lifecycle:

```text
CREATE
 ↓
REVIEW
 ↓
START
 ↓
RUN
 ↓
PAUSE / RESUME
 ↓
COMPLETE
```

---

# 11. Agent Creation

User provides:

```text
Agent Name
Instrument
Timeframe
Initial Capital
Maximum Risk Per Trade
Maximum Position Exposure
Maximum Daily Loss
Natural Language Strategy
```

Example:

```text
Agent:
Reliance Momentum Agent

Instrument:
RELIANCE

Timeframe:
15m

Capital:
₹1,00,000

Risk:
2%

Strategy:
"I want a momentum strategy. Prefer bullish trends
using EMA and RSI. Avoid weak momentum and don't
take excessive risk."
```

Gemini converts this into a structured **agent mandate/configuration**.

Example:

```json
{
  "instrument": "RELIANCE",
  "timeframe": "15m",
  "strategy_style": "momentum",
  "objectives": [
    "capture bullish momentum",
    "avoid weak setups"
  ],
  "preferred_indicators": [
    "EMA9",
    "EMA20",
    "RSI14",
    "MACD"
  ]
}
```

This configuration is the agent's **mandate**, not a replacement for agent reasoning.

---

# 12. Agent Review

Before simulation starts, show the user:

```text
Strategy Style
Objective
Preferred Indicators
Instrument
Timeframe
Risk Limits
```

Buttons:

```text
EDIT
START SIMULATION
```

The user must explicitly start the simulation.

---

# 13. Technical Indicators

Keep the indicator library intentionally small.

Implement:

### EMA

```text
EMA 9
EMA 20
```

### SMA

```text
SMA 50
```

### RSI

```text
RSI 14
```

### MACD

```text
Fast EMA = 12
Slow EMA = 26
Signal = 9
```

Also expose:

```text
Open
High
Low
Close
Volume
```

Potential future indicators:

```text
ATR
Bollinger Bands
```

Do not implement initially.

---

# 14. Indicator Calculation

Calculate all indicators deterministically in Python.

Use:

```text
Pandas
NumPy
SciPy
```

Optionally:

```text
pandas-ta-classic
```

For important indicators, ensure calculations are independently tested/verified.

Gemini receives calculated values.

Do not ask Gemini to calculate technical indicators.

---

# 15. Market Regime

Implement a deterministic descriptive market-state classifier providing contextual market context.

### Core Architecture Principle

Market regime classification is **purely descriptive context**, NOT trading instructions or a mechanical trading strategy.

The deterministic backend classifies the market environment and provides structured quantitative evidence to Gemini. Gemini remains solely responsible for synthesizing this market state together with the user mandate, portfolio exposure, position history, and risk parameters to decide `BUY` / `SELL` / `HOLD`.

The system produces two orthogonal, deterministic classifications:

1. **TrendRegime:** `BULLISH` | `BEARISH` | `SIDEWAYS`
2. **VolatilityRegime:** `HIGH` | `NORMAL` | `LOW`

---

### Trend Regime Classification (3-of-4 Majority Voting)

Evaluates four technical indicator conditions on candle $t$:

1. **Close vs SMA50:**
   - Bullish: $\text{Close}_t > \text{SMA50}_t$
   - Bearish: $\text{Close}_t < \text{SMA50}_t$
2. **EMA9 vs EMA20:**
   - Bullish: $\text{EMA9}_t > \text{EMA20}_t$
   - Bearish: $\text{EMA9}_t < \text{EMA20}_t$
3. **MACD Line vs Zero:**
   - Bullish: $\text{MACD}_t > 0$
   - Bearish: $\text{MACD}_t < 0$
4. **RSI14 vs 50:**
   - Bullish: $\text{RSI14}_t > 50$
   - Bearish: $\text{RSI14}_t < 50$

**Classification Rule:**
- If $\ge 3$ signals are Bullish $\implies$ `TrendRegime = BULLISH`
- If $\ge 3$ signals are Bearish $\implies$ `TrendRegime = BEARISH`
- Otherwise (mixed votes, ties, or insufficient history) $\implies$ `TrendRegime = SIDEWAYS`

---

### Volatility Regime Classification (100-Bar Historical Rolling Percentiles)

Evaluates normalized volatility using $\text{ATRP14}_t = (\text{ATR14}_t / \text{Close}_t) \times 100$:

1. **Lookback Distribution:**
   - Uses the previous 100 VALID $\text{ATRP14}$ observations strictly before candle $t$ (strictly historical observations to prevent look-ahead bias).
2. **Empirical Thresholds:**
   - $p_{20}$ = 20th percentile of the previous 100 VALID $\text{ATRP14}$ observations strictly before candle $t$
   - $p_{80}$ = 80th percentile of the previous 100 VALID $\text{ATRP14}$ observations strictly before candle $t$

**Classification Rule:**
- If fewer than 100 valid preceding $\text{ATRP14}$ observations exist strictly before candle $t$:
  `volatility_regime = None` (Do NOT default to `NORMAL`).
- If $\text{ATRP14}_t \le p_{20} \implies$ `VolatilityRegime = LOW`
- If $\text{ATRP14}_t \ge p_{80} \implies$ `VolatilityRegime = HIGH`
- Otherwise ($p_{20} < \text{ATRP14}_t < p_{80}$) $\implies$ `VolatilityRegime = NORMAL`

---

### Warmup & Missing Data Semantics

- **Trend Regime Warmup:** Requires valid values for SMA50, EMA20, EMA9, MACD, and RSI14 at candle $t$. If fewer than 50 bars exist such that indicators are incomplete/None, `trend_regime = None`.
- **Volatility Regime Warmup:** Requires exactly the previous 100 VALID $\text{ATRP14}$ observations strictly before candle $t$ (i.e. at least 114 bars of history). If fewer than 100 valid preceding $\text{ATRP14}$ observations exist: `volatility_regime = None`.
- Under no circumstances does the engine guess, hallucinate, or default missing historical distributions to `NORMAL`.

---

### Separation of Responsibilities

- **Deterministic Backend:** Authoritative for market data, indicator math, regime classification, risk limits, portfolio accounting, and order execution.
- **Gemini Agent:** Interprets market state, indicators, regimes, and mandate to reason and generate trade actions. Never asks backend for trade signals.



---

# 16. Market Data Architecture

This is an important final decision.

Do **not** require the user to create a broker account.

Do not use:

* Upstox
* Angel One
* Zerodha
* Dhan

as mandatory data providers.

The application should initially use:

> **OpenChart / NSE public charting data**

through a dedicated provider adapter.

OpenChart is an open-source Python library that accesses NSE's public charting endpoints without requiring a broker account/API key.

Use it only through the backend.

Do not call it directly from the frontend.

---

# 17. Custom Market Data API

Build our own internal market-data service around the OpenChart provider.

Architecture:

```text
Next.js
   ↓
FastAPI
   ↓
MarketDataService
   ↓
NSEPublicProvider
   ↓
OpenChart
   ↓
NSE public charting endpoints
```

The rest of the application must **not know OpenChart exists**.

---

# 18. MarketDataProvider Abstraction

Create:

```python
class MarketDataProvider:
    def get_instruments(...)
    def get_historical_data(...)
    def get_latest_data(...)
```

Implement:

```text
NSEPublicProvider
```

using OpenChart.

This makes it possible to replace the provider later.

---

# 19. Historical Data Strategy

Do **not** manually populate all historical data before development.

Use:

> **On-demand fetch + persistent storage.**

Flow:

```text
User requests data
        ↓
Check PostgreSQL
        ↓
Is data available?
   /          \
 YES           NO
  │             │
  │             ▼
  │        OpenChart/NSE
  │             │
  │             ▼
  │        Validate data
  │             │
  │             ▼
  │        Store in DB
  │             │
  └──────┬──────┘
         ▼
    Return data
```

This makes PostgreSQL a **persistent local cache/data store**.

---

# 20. Database Is the Source of Truth

Use PostgreSQL as the primary persistent store for:

* historical OHLCV
* agents
* strategies/configurations
* simulations
* orders
* trades
* positions
* portfolio snapshots
* agent decisions
* tool calls
* Gemini usage

Do not make Parquet mandatory.

Parquet may optionally be used for bulk import/export later.

---

# 21. Historical Data Table

Create a table such as:

```text
candles
```

Fields:

```text
id
instrument_id
timestamp
timeframe
open
high
low
close
volume
```

Unique constraint:

```text
instrument_id
timeframe
timestamp
```

Index:

```text
instrument_id
timeframe
timestamp
```

This must allow efficient range queries.

---

# 22. Instruments Table

Fields:

```text
id
symbol
name
exchange
instrument_type
```

Example:

```text
RELIANCE
TCS
INFY
NIFTY 50
BANK NIFTY
```

---

# 23. Data Range Metadata

Maintain metadata such as:

```text
market_data_ranges
```

Fields:

```text
instrument
timeframe
earliest_timestamp
latest_timestamp
last_updated
```

This allows the application to quickly determine whether data needs to be fetched.

---

# 24. Missing Data Handling

If a requested range is partially available:

```text
Requested:
2022 → 2025

Database:
2023 → 2025
```

The service should identify:

```text
2022 → missing
```

and fetch only that range.

Do not redownload data that already exists.

---

# 25. Data Validation

Before storing fetched candles:

Validate:

```text
timestamp
open
high
low
close
volume
```

Reject:

* malformed rows
* impossible OHLC relationships
* duplicate timestamps
* invalid prices
* invalid timestamps

Use PostgreSQL uniqueness constraints as an additional duplicate safeguard.

---

# 26. Backtesting Data Lock

Before a simulation starts:

```text
User requests:
RELIANCE
15m
2023-01-01 → 2025-12-31

        ↓

Ensure entire range exists
        ↓
Fetch missing data
        ↓
Validate completeness
        ↓
LOCK simulation dataset
        ↓
START
```

Once the simulation starts, it must use the stored dataset.

Do not fetch new historical data during an active simulation.

This ensures reproducibility.

---

# 27. Historical Data Size

Do not worry about PostgreSQL becoming too large.

Initial supported universe:

```text
7 stocks
3 indices
```

Even several years of intraday candles for this limited universe is manageable on a normal development machine.

The system should still fetch data progressively instead of downloading everything upfront.

---

# 28. Data Updater

Support a background/update operation for supported instruments.

Conceptually:

```text
Every appropriate interval
        ↓
Check latest stored candle
        ↓
Fetch newer completed candles
        ↓
Validate
        ↓
Insert into PostgreSQL
```

Do not aggressively poll NSE.

Use conservative request rates.

---

# 29. Live Simulation

Do not claim exchange-grade real-time infrastructure.

The initial "live" experience is:

> **simulated live/replay using available market data**

For a 15-minute strategy:

```text
09:15 candle
 ↓
Agent evaluates
 ↓
09:30 candle
 ↓
Agent evaluates
 ↓
09:45 candle
 ↓
...
```

For future current-market support, the MarketDataProvider abstraction can expose latest/current data.

---

# 30. Trading Simulator

The simulator must support:

```text
BUY
SELL
HOLD
```

Maintain:

```text
cash
positions
orders
trades
portfolio value
realized P&L
unrealized P&L
```

---

# 31. Execution Model

For historical simulation:

If a decision is made using candle `t`, do **not** execute at the same candle close.

For a market order:

> Execute at the next available candle's open price.

This avoids look-ahead/execution bias.

---

# 32. Transaction Costs

Support configurable:

```text
brokerage
transaction costs
slippage
```

Store:

```text
gross P&L
transaction costs
net P&L
```

Use reasonable configurable defaults.

Do not claim exact brokerage/tax reproduction unless verified.

---

# 33. Slippage

Default:

```text
0.05%
```

BUY:

```text
market price × (1 + slippage)
```

SELL:

```text
market price × (1 - slippage)
```

Make it configurable.

---

# 34. Stop Loss & Take Profit Auto-Triggers

Stop-loss and take-profit enforcement must be deterministic and fully automated without calling Gemini.

### Trigger Detection from Completed Candle OHLC Extremes
Triggers are evaluated on completed candles for active open positions:
- **Stop Loss:** Long position triggers when `candle.low <= position.stop_loss`.
- **Take Profit:** Long position triggers when `candle.high >= position.take_profit`.

### Dual-Touch Resolution (Same Candle)
An OHLC candle can potentially span both the stop-loss and take-profit levels (`candle.low <= position.stop_loss` AND `candle.high >= position.take_profit`).
Because standard OHLC summary bars do not reveal intrabar price sequencing:
- **`STOP_LOSS` takes strict precedence.**
- This is a conservative, deterministic rule that eliminates optimistic P&L bias.

### Execution Model: Separation of Trigger Candle vs Execution/Fill Candle
- **A trigger does NOT itself define the fill price.**
- A trigger on candle $t$ creates an automatic simulated market exit order (`OrderSide.SELL`).
- `decision_price` on an automatic exit order is metadata only (recording the SL or TP threshold at trigger time); it is **NOT** the fill price.
- The **"trigger candle"** ($t$, where $Low \le SL$ or $High \ge TP$) and the **"execution/fill candle"** ($t+1$, where the market exit order fills at Open) are strictly **different candles**.
- Automatic SL/TP exit orders use the standard Phase 5B execution model:
  - Fill price = Next available candle OPEN ($P_{t+1, \text{open}}$) with standard directional slippage applied:
    $$P_{\text{exec}} = P_{t+1, \text{open}} \times (1 - \text{slippage\_pct})$$
  - Standard transaction costs: $\text{nominal} \times \text{brokerage\_rate} + \text{fixed\_fee}$.
  - Standard authoritative `PortfolioTracker.close_or_reduce_position()` accounting.
- **No separate intrabar fill model** or separate SL/TP slippage/accounting logic is introduced.
- `exit_reason` recorded in `TradeRecord` and `ExecutionResult` must be exactly:
  - `STOP_LOSS`
  - `TAKE_PROFIT`

---

# 35. Deterministic Sequencing & Replay Simulation Cycle

### Unified Per-Candle Simulation Sequence
For each simulation candle $t$ (timestamp $T_k$):
1. **Execute pending automatic exits at current candle OPEN:**
   - Execute any pending `STOP_LOSS` / `TAKE_PROFIT` automatic exit orders against the current candle's open price ($P_{t, \text{open}}$) with directional slippage and fees via `ExecutionEngine.execute_order()`.
2. **Execute pending strategy orders at current candle OPEN:**
   - Execute any pending strategy orders (e.g. baseline crossover BUY or manual SELL) against the current candle's open price ($P_{t, \text{open}}$) with directional slippage and fees via `ExecutionEngine.execute_order()`.
3. **Update authoritative portfolio state:**
   - Update `PortfolioTracker` cash balances, position cost bases, and closed trade records resulting from all fills at Step 1 and Step 2.
4. **Complete current candle and mark to market at CLOSE:**
   - Candle $t$ completes (OHLCV values fully formed). Mark active positions to market at the completed candle's close price ($P_{t, \text{close}}$) to update unrealized P&L and total equity.
5. **Evaluate completed-candle SL/TP trigger conditions:**
   - Evaluate completed candle $t$ OHLC extremes against active remaining positions ($Low \le SL$, $High \ge TP$).
   - If dual-touch occurs on a candle, `STOP_LOSS` takes strict precedence.
   - Queue any newly generated automatic exit orders for the next available candle OPEN ($t+1$).
6. **Evaluate strategy signals and queue orders for next candle OPEN:**
   - Calculate indicators and evaluate strategy logic using information available strictly through completed candle $t$.
   - If a valid trading signal is generated, size and validate the order via `RiskEngine`, then queue the order for execution at the next available candle OPEN ($t+1$).

### Important Same-Symbol Precedence Rule
- If a symbol has a pending automatic `STOP_LOSS` or `TAKE_PROFIT` exit order scheduled for the current candle OPEN, **no pending strategy order (BUY or SELL) for that same symbol may execute at that OPEN**.
- The automatic exit takes strict precedence.
- Strategy logic is prohibited from reopening or scaling a position that is simultaneously being liquidated by an automated exit.
- Any conflicting strategy order for that symbol scheduled for the same OPEN is rejected without side effects on cash or portfolio state.

### Strict Chronological & No-Look-Ahead Rules
- **Information Horizon:** At decision time $t$, only market and portfolio information available up to and including candle $t$ may be used.
- **Zero Future Data:** No future candle OHLC, future indicator values, future trade executions, future portfolio equity, or external data may be accessed.
- **Execution Separation:** Orders generated at candle $t$ execute no earlier than candle $t+1$ OPEN ($P_{t+1, \text{open}}$). Execution at candle $t$ close is strictly forbidden.
- **Clock Authority:** The simulation timestamp advances strictly from the historical candle stream ($T_0, T_1, \dots, T_n$), never from wall-clock time (`datetime.now()`).

### Idempotency Invariants
- A simulation timestamp/candle may be processed exactly once.
- Repeated playback or control requests (e.g., duplicate resume or step signals) must never re-process an already processed candle.
- Re-processing an identical timestamp is strictly guarded against to prevent corrupted cash balances, duplicate orders, or double-counted transaction fees.

### Pending Exit Deduplication Invariants
- **No duplicate exits:** A position that already has a pending automatic SL/TP exit order **MUST NOT** generate another automatic exit order while that exit is pending.
- **Terminal state:** Once the pending exit executes and the position is closed, no further triggers may be generated for that position.
- **Agent notification:** The reasoning agent is informed after execution that the position was closed by `STOP_LOSS` or `TAKE_PROFIT`.

---

# 36. Risk Engine

Gemini proposes orders.

The risk engine has final authority.

Required controls:

```text
maximum risk per trade
maximum position exposure
maximum portfolio exposure
maximum daily loss
available cash
position size
stop-loss validity
take-profit validity
order validity
```

Default:

```text
Initial capital: ₹1,00,000
Max risk/trade: 2%
Max position exposure: 25%
Max daily loss: 5%
```

Make configurable.

---

# 37. Agent Tools

Implement:

```text
get_market_data()
get_indicators()
get_market_regime()
get_position()
get_portfolio()
get_trade_history()
calculate_position_size()
place_simulated_order()
close_simulated_position()
```

Gemini accesses the environment through these tools.

---

# 38. Tool Responsibilities

### get_market_data

Returns:

```text
recent OHLCV
current price
recent price change
volume
```

### get_indicators

Returns:

```text
EMA9
EMA20
SMA50
RSI14
MACD
MACD signal
MACD histogram
```

### get_market_regime

Returns:

```text
trend_regime (BULLISH / BEARISH / SIDEWAYS)
volatility_regime (HIGH / NORMAL / LOW)
trend_signals (close_vs_sma50, ema9_vs_ema20, macd_vs_zero, rsi14_vs_50, bullish_votes, bearish_votes)
volatility_metrics (current_atrp14, p20_threshold, p80_threshold, sample_count)
```


### get_position

Returns:

```text
position status
quantity
entry
current price
stop loss
take profit
unrealized P&L
```

### get_portfolio

Returns:

```text
cash
portfolio value
P&L
daily P&L
exposure
available capital
```

### get_trade_history

Returns recent trades.

### calculate_position_size

Deterministically calculates quantity based on:

```text
capital
risk
entry
stop-loss
```

### place_simulated_order

Submits order to risk engine.

### close_simulated_position

Submits close request to risk/execution layer.

---

### Tool Layer Boundary & Staged Order Semantics (Phase 7 vs Phase 8)

1. **Tool-Call Responsibility:**
   Phase 7 tools are responsible strictly for typed tool-call handling, validation, and staging orders.
2. **Order Staging Limit:**
   `place_simulated_order()` and `close_simulated_position()` may stage at most one order per candle according to the frozen Phase 7 rule. Subsequent order calls on the same candle are rejected.
3. **No AgentDecision Processing in Phase 7:**
   Phase 7 MUST NOT interpret, generate, reconcile, or execute `AgentDecision` objects. Phase 7 contains zero `AgentDecision`-specific controller logic.
4. **Phase 8 Reconciliation Responsibility:**
   `AgentDecision`/tool-call reconciliation is exclusively a Phase 8 Gemini agent-loop responsibility.
5. **Structured State Exposure:**
   Phase 7 must expose enough structured information (e.g., whether an order was staged, the staged `order_id`, and staging status in the execution context and tool execution results) for Phase 8 to determine whether an order was already staged, but Phase 7 must not contain `AgentDecision`-specific controller logic.

---

# 39. Agent Decision Schema

Gemini must return structured output.

Use Pydantic.

Schema:

```python
class AgentDecision:
    action: BUY | SELL | HOLD
    confidence: float
    quantity: Optional[int]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    reason: str
    observations: list[str]
    tools_used: list[str]
```

Validate:

```text
0 <= confidence <= 1
quantity > 0 if supplied
prices > 0
reason != empty
```

Malformed output must be rejected.

---

# 40. Decision Meaning

### BUY

Open/increase long position.

### SELL

Reduce/close long position.

### HOLD

Take no action.

The agent must be allowed to remain flat.

Do not force trades.

---

# 41. Agent State / Memory

Maintain compact structured state:

```text
agent_id
instrument
timeframe
position
entry_price
stop_loss
take_profit
portfolio_value
cash
current_pnl
market_regime
last_decision
last_reason
recent_decisions
recent_trades
```

Keep recent history bounded.

Example:

```text
last 5 decisions
last 10 trades
```

Do not send the entire conversation history to Gemini on every cycle.

---

# 42. Agent Decision Loop

Each decision cycle:

```text
Market event
    ↓
Update market state
    ↓
Check deterministic stop-loss/take-profit
    ↓
Determine whether Gemini decision is required
    ↓
If not required:
    continue
    ↓
If required:
    Gemini observes state
    ↓
    Gemini uses tools if needed
    ↓
    Gemini produces structured decision
    ↓
Pydantic validation
    ↓
Risk engine
    ↓
Simulated execution
    ↓
Update state
    ↓
Log decision
```

---

# 43. Gemini Failure

If Gemini fails:

```text
invalid response
timeout
API error
rate limit
```

Default:

```text
PAUSE AGENT
```

Do not fabricate a BUY/SELL decision.

UI should show:

```text
Agent paused:
Gemini decision unavailable.
```

User can resume.

---

# 44. Security

Never execute arbitrary Gemini-generated code.

Never use:

```text
eval()
exec()
arbitrary shell commands
arbitrary SQL
```

Gemini may only invoke explicitly registered tools.

Validate all tool parameters.

Never commit API keys.

Use:

```text
.env
.env.example
```

---

# 45. Gemini API Key

For development:

```text
GEMINI_API_KEY=
```

in `.env`.

Do not store keys in PostgreSQL.

For a later multi-user deployment, implement secure per-user key/session handling.

Do not build complicated authentication for MVP.

---

# 46. Database

Use:

```text
PostgreSQL
SQLAlchemy 2.x
Alembic
```

Tables:

```text
users
instruments
candles
market_data_ranges
agents
agent_configs
simulation_runs
orders
trades
positions
portfolio_snapshots
agent_decisions
agent_tool_calls
agent_usage
```

---

# 47. Redis

Use Redis only for:

```text
temporary simulation state
market-data cache
rate limiting
WebSocket/session state
```

PostgreSQL remains persistent source of truth.

---

# 48. Backend Stack

Use:

```text
Python 3.12+
FastAPI
Pydantic v2
Uvicorn
SQLAlchemy 2.x
Alembic
Pandas
NumPy
SciPy
google-genai
```

Optional:

```text
pandas-ta-classic
```

---

# 49. Frontend Stack

Use:

```text
Next.js
TypeScript
Tailwind CSS
shadcn/ui
Lightweight Charts
TanStack Query
```

Use native WebSockets for real-time updates.

---

# 50. Development Tools

Python:

```text
uv
Ruff
Pyright
pytest
pytest-asyncio
```

Node:

```text
pnpm
ESLint
Prettier
Vitest
```

Infrastructure:

```text
Docker
Docker Compose
Git
GitHub
```

Do not use Kubernetes.

Do not introduce microservices.

---

# 51. Backend API

Implement approximately:

```text
GET    /api/v1/instruments

GET    /api/v1/market-data/{symbol}/historical
GET    /api/v1/market-data/{symbol}/latest

GET    /api/v1/indicators/{symbol}

POST   /api/v1/agents
GET    /api/v1/agents
GET    /api/v1/agents/{id}

POST   /api/v1/agents/{id}/start
POST   /api/v1/agents/{id}/pause
POST   /api/v1/agents/{id}/resume
POST   /api/v1/agents/{id}/stop

POST   /api/v1/simulations
GET    /api/v1/simulations/{id}

POST   /api/v1/simulations/{id}/start
POST   /api/v1/simulations/{id}/pause
POST   /api/v1/simulations/{id}/resume
POST   /api/v1/simulations/{id}/step
POST   /api/v1/simulations/{id}/stop

GET    /api/v1/simulations/{id}/trades
GET    /api/v1/simulations/{id}/performance
GET    /api/v1/simulations/{id}/decisions
```

WebSocket:

```text
/ws/simulations/{simulation_id}
```

---

# 52. WebSocket Events

Use events:

```text
candle_update
agent_started
agent_analyzing
tool_call
tool_result
agent_decision
risk_check
order_executed
position_updated
portfolio_updated
simulation_complete
error
```

Frontend should update without constant polling.

---

# 53. Frontend Screens

Implement:

## Dashboard

Current running simulation.

## Create Agent

Create custom agent.

## Agent Details

View configuration.

## Simulation

Replay/backtest controls.

## Trade History

All trades.

## Performance

Metrics and charts.

## Agent Decisions

Decision/rationale history.

## Settings

Gemini configuration.

---

# 54. Dashboard Layout

Main chart:

```text
Candlesticks
EMA9
EMA20
SMA50
Buy markers
Sell markers
Stop-loss
Take-profit
```

Right-side agent panel:

```text
Agent Name
Status
Market Regime
Position
Current Signal
Confidence
Entry
Current Price
Stop Loss
Take Profit
P&L
```

Bottom:

```text
Performance
Trade History
Agent Activity
```

---

# 55. Agent Activity

Show concise operational events:

```text
10:15
Agent analyzing market

10:15
Retrieved indicators

10:15
Market regime: BULLISH

10:15
Decision: BUY

10:15
Risk check: PASSED

10:15
Order executed
```

Do NOT display private chain-of-thought.

Display only concise observations and decision rationale.

---

# 56. Example Agent Decision UI

```text
10:15

Market Regime
Trend: BULLISH | Volatility: NORMAL


Observations
✓ EMA9 above EMA20
✓ MACD positive
⚠ RSI elevated

Decision
BUY

Confidence
78%

Entry
₹1452

Stop Loss
₹1423

Take Profit
₹1490

Risk Check
PASSED

Execution
20 shares bought
```

---

# 57. Simulation Controls & State Machine

Provide:

```text
START
PAUSE
RESUME
STOP
RESET
STEP
```

Speed:

```text
0.5x
1x
2x
5x
10x
```

Display:

```text
simulation date/time
progress
current candle
```

### Simulation State Machine & Control Semantics
- **Valid Transitions:**
  - `CREATED` $\to$ `RUNNING` (via `START`)
  - `RUNNING` $\to$ `PAUSED` (via `PAUSE`)
  - `PAUSED` $\to$ `RUNNING` (via `RESUME`)
  - `RUNNING` or `PAUSED` $\to$ `STOPPED` (via `STOP`)
  - `RUNNING` $\to$ `COMPLETED` (automatically when dataset is exhausted)
- **Control Idempotency & Safety Rules:**
  - `START` on an already `RUNNING` simulation is an idempotent no-op.
  - `RESUME` on an already `RUNNING` simulation is an idempotent no-op.
  - `PAUSE` on an already `PAUSED` simulation is an idempotent no-op.
  - `STEP` is valid **only** while `PAUSED`. It advances the simulation clock by exactly 1 completed candle cycle and freezes again in `PAUSED`.
  - Calling `START` or `RESUME` on a terminal state (`STOPPED` or `COMPLETED`) must be rejected with an error (400 Bad Request: invalid state transition).
  - `STOP` is strictly terminal. Once stopped, the simulation cannot be resumed.

### Simulation Playback Persistence Model
- **Active Playback State:** Current simulation timestamp, step index, playback speed multiplier, and lifecycle status are tracked in the active simulation session (in-memory controller and/or Redis).
- **Periodic & Event Synchronization:** Progress, current timestamp, and runtime metrics are synchronized into PostgreSQL (`SimulationRun.metrics` JSON, `PortfolioSnapshot` records, and `orders`/`trades` tables) upon pause, snapshot intervals, and completion.
- **Persistent Source of Truth:** PostgreSQL remains the authoritative persistent store for all simulation runs, orders, trades, snapshots, and final evaluated metrics.

### Backtest Reproducibility Invariant
- **Bit-for-Bit Determinism:** Replaying an identical locked dataset under identical configuration parameters (initial capital, execution slippage/brokerage, risk limits, and strategy rules) must produce **identical** trades, fill prices, transaction costs, portfolio valuations, and performance metrics.
- **Playback Independence:** Simulation results must be strictly independent of playback speed (0.5x vs 10x) and execution mode (continuous playback vs bar-by-bar stepping).

---

# 58. Performance Metrics

Calculate:

```text
Initial Capital
Final Portfolio Value
Net P&L
Net Return %
Gross P&L
Transaction Costs
Number of Trades
Winning Trades
Losing Trades
Win Rate
Average Win
Average Loss
Profit Factor
Maximum Drawdown
```

Optional later:

```text
Sharpe Ratio
Sortino Ratio
```

---

# 59. Baseline Strategy

Implement a deterministic benchmark baseline:

```text
BUY:
EMA9 crosses above EMA20

SELL:
EMA9 crosses below EMA20

Stop Loss:
2%
```

### Exact Mathematical Crossover Definition
- **Bullish Crossover at candle $t$ (BUY Signal):**
  $$\text{EMA9}_{t-1} \le \text{EMA20}_{t-1} \quad \text{AND} \quad \text{EMA9}_t > \text{EMA20}_t$$
- **Bearish Crossover at candle $t$ (SELL Signal):**
  $$\text{EMA9}_{t-1} \ge \text{EMA20}_{t-1} \quad \text{AND} \quad \text{EMA9}_t < \text{EMA20}_t$$
- **Equality at candle $t$:** $\text{EMA9}_t == \text{EMA20}_t$ does not constitute a crossover and results in `HOLD`.
- **Warmup & Validity Invariant:**
  - EMA9 requires 9 candles; EMA20 requires 20 candles (index 19 is the first valid EMA20 bar).
  - A valid crossover at candle $t$ requires valid non-None EMA9 and EMA20 values at both candle $t-1$ and candle $t$.
  - The earliest bar where a crossover can be detected is **index 20 (the 21st candle)**.
  - Prior to index 20, the strategy deterministically emits `HOLD`.

### Single-Position Long-Only Benchmark Semantics
- **Spot Long-Only Model:** Short selling is not supported.
- **Bearish Crossover while Flat:** If a bearish crossover occurs when holding no open position, the strategy emits `HOLD` (no action; never short).
- **Bullish Crossover while Already Long:** If a bullish crossover occurs when already holding an active long position, the strategy emits `HOLD` (no duplicate buy; no scaling).
- **Position Liquidation:** A bearish crossover while long generates a `SELL` order to close the entire open position.

### 2% Stop-Loss Attachment (Decision-Price Based)
- When a BUY order is generated at completed candle $t$, a 2% protective stop loss is attached:
  $$\text{stop\_loss} = \text{round}(\text{candle}_t.\text{close} \times 0.98, 2)$$
- This value is set on `OrderRequest.stop_loss` at order submission time and passed directly through the existing Phase 5 risk and execution path into `PortfolioTracker.open_or_increase_position(..., stop_loss=order.stop_loss)`.
- Existing Phase 5 execution semantics remain 100% frozen and unmodified.

### Strict Decoupling from Market Regime Classifier
- The deterministic market-regime classifier (`TrendRegime`, `VolatilityRegime`) is **descriptive context only**.
- The baseline strategy has **zero dependency** on `TrendRegime` or `VolatilityRegime`.
- The baseline must evaluate strictly and exclusively on the mathematical EMA 9/20 crossover and 2% SL.

### Equal Treatment under RiskEngine
- Baseline orders route through the exact same `RiskEngine` position sizing (`RiskEngine.calculate_position_size()`) and pre-trade validation (`RiskEngine.validate_order()`) as AI agents, ensuring fair and rigorous benchmark comparison.

Run the baseline and AI agent on the same historical period.

Compare:

```text
Return
P&L
Win Rate
Maximum Drawdown
Trades
Transaction Costs
```

This is an important evaluation feature.

---

# 60. Gemini Usage Metrics

Track:

```text
Gemini calls
Input tokens
Output tokens
Total tokens
Average tokens/decision
Average latency
Estimated cost
```

Example:

```text
Agent Decisions: 27
Gemini Calls: 27
Tokens: 31,820
Average latency: 1.3s
```

This demonstrates the event-driven/token-efficient design.

---

# 61. Logging

Use structured logging, preferably:

```text
structlog
```

Log:

```text
timestamp
agent_id
simulation_id
market state
tools used
decision
confidence
risk result
execution result
Gemini latency
input tokens
output tokens
```

---

# 62. Testing

Use:

```text
pytest
pytest-asyncio
Vitest
```

Test:

### Quantitative

```text
EMA
RSI
MACD
SMA
market regime
```

### Trading

```text
position sizing
portfolio accounting
P&L
transaction costs
slippage
stop-loss
take-profit
```

### Risk

```text
max position
max exposure
daily loss
invalid orders
```

### Agent

```text
valid Gemini response
malformed response
invalid quantity
invalid price
invalid action
risk violation
```

### Simulation

Same input dataset should produce reproducible simulator results where deterministic.

---

# 63. No Look-Ahead Bias

Mandatory.

At simulation time `T`, the agent can only access information available at `T`.

It cannot access future:

* candles
* prices
* indicators
* trades
* news

The simulation engine must process data chronologically.

---

# 64. Backtest Dataset

Use different market conditions:

```text
bull market
bear market
sideways market
high volatility
low volatility
```

Evaluate:

```text
agent consistency
risk compliance
trade execution
P&L
drawdown
tool usage
Gemini efficiency
```

Do not evaluate solely on profitability.

---

# 65. Data Storage Strategy

Final approach:

### Do NOT prepopulate everything.

Use:

> **Fetch on demand → validate → store permanently → reuse.**

The first time the user requests:

```text
RELIANCE
15m
2023 → 2025
```

the service fetches missing data.

Afterward:

```text
PostgreSQL
    ↓
already available
    ↓
no external request
```

This gradually builds the local market-data repository.

---

# 66. Initial Data Population

For development, start small.

First:

```text
RELIANCE
15m
6–12 months
```

Get the entire system working.

Then add:

```text
TCS
INFY
HDFCBANK
ICICIBANK
SBIN
ITC

NIFTY 50
BANK NIFTY
NIFTY IT
```

Then expand historical ranges.

Do not download five years for everything before the application works.

---

# 67. Data Update Strategy

Have a data-update process:

```text
Check latest stored candle
        ↓
Request newer completed data
        ↓
Validate
        ↓
Insert into PostgreSQL
```

Use conservative request frequency.

Do not aggressively query NSE.

---

# 68. Historical Simulation

Before starting:

```text
Check complete data range
        ↓
Fetch missing data
        ↓
Validate
        ↓
Start simulation
```

Once started:

> Simulation reads only from PostgreSQL.

No external data retrieval during the simulation.

---

# 69. Project Directory

Use a monorepo:

```text
nse-ai-trader/
│
├── apps/
│   ├── web/
│   │   ├── app/
│   │   ├── components/
│   │   ├── lib/
│   │   └── ...
│   │
│   └── api/
│       ├── app/
│       │   ├── api/
│       │   ├── agent/
│       │   ├── market/
│       │   ├── indicators/
│       │   ├── risk/
│       │   ├── trading/
│       │   ├── simulation/
│       │   ├── database/
│       │   └── core/
│       │
│       └── tests/
│
├── data/
├── docs/
├── scripts/
├── docker/
├── docker-compose.yml
├── README.md
├── .env.example
└── .gitignore
```

---

# 70. Database Architecture

Use:

```text
PostgreSQL
    │
    ├── Market Data
    │
    ├── Agent Data
    │
    ├── Simulation Data
    │
    ├── Trading Data
    │
    └── Evaluation Data
```

Redis:

```text
temporary state
cache
rate limiting
```

---

# 71. UI Design Direction

Make it look like a:

> **modern quantitative trading terminal**

Use:

* clean cards
* professional typography
* compact tables
* restrained animations
* clear financial colors
* responsive layout

Avoid:

* cyberpunk styling
* excessive gradients
* excessive animations
* huge decorative elements

Heimdall already has a distinct AI/cyberpunk identity. This project should have a **financial/quantitative identity**.

---

# 72. Authentication

Do not build complex authentication for MVP.

The project can initially be single-user/local.

If later required, add proper authentication.

---

# 73. Cost

The entire development stack should be usable without paying for broker/data accounts.

Software:

```text
Next.js             FREE
TypeScript          FREE
FastAPI             FREE
Python              FREE
PostgreSQL          FREE
Redis               FREE locally
Pandas              FREE
NumPy               FREE
Gemini              FREE tier initially
Docker              FREE for this use case
Git/GitHub          FREE tier
OpenChart            OPEN SOURCE
```

Market data comes initially from the public NSE/OpenChart route.

Do not require:

```text
Upstox account
Angel One account
Zerodha account
Dhan account
```

---

# 74. Data Disclaimer

The project is for:

> **Educational/research and simulated trading purposes.**

Do not present it as:

* professional trading infrastructure
* guaranteed profitable system
* investment advice
* exchange-grade live trading system

Do not redistribute NSE data as a standalone public data service.

Use conservative request rates and respect the applicable NSE/OpenChart terms.

---

# 75. Things NOT to Build Initially

Do not implement:

```text
real-money trading
broker integration
options
futures
commodities
crypto
international markets
30+ indicators
price prediction ML
reinforcement learning
multi-agent swarm
MCP
multiple LLM providers
Ollama
Kubernetes
microservices
complex authentication
complex news scraping
```

These can be future extensions.

---

# 76. Why We Are NOT Using MCP

Heimdall already demonstrates MCP.

For this project, use:

```text
Gemini Function Calling
        ↓
Typed Trading Tools
```

Do not add MCP just for the sake of using another buzzword.

The projects should demonstrate different engineering capabilities.

---

# 77. Why We Are NOT Using Multiple LLMs

Use Gemini deliberately.

Heimdall already demonstrates:

```text
Gemini
Groq
Ollama
```

This project should instead demonstrate:

> **LLM reasoning integrated with a quantitative trading environment.**

---

# 78. Development Order

Implement in this exact order:

```text
PHASE 1
Repository + project scaffolding

PHASE 2
PostgreSQL + SQLAlchemy + Alembic

PHASE 3
Instrument model

PHASE 4
MarketDataProvider abstraction

PHASE 5
OpenChart/NSE provider

PHASE 6
Historical data ingestion + persistence

PHASE 7
Market-data API

PHASE 8
Candlestick frontend

PHASE 9
Indicator engine

PHASE 10
Trading portfolio/accounting

PHASE 11
Risk engine

PHASE 12
Simulation engine

PHASE 13
Agent tool layer

PHASE 14
Gemini agent integration

PHASE 15
Event-driven agent loop

PHASE 16
Agent creation/review UI

PHASE 17
Trading dashboard

PHASE 18
Historical replay

PHASE 19
Baseline comparison

PHASE 20
Gemini usage/evaluation metrics

PHASE 21
Automated testing

PHASE 22
UI polish

PHASE 23
Docker

PHASE 24
Documentation
```

---

# 79. First Milestone

Do **not** start with Gemini.

First make this work:

```text
Select RELIANCE
       ↓
Request historical 15m data
       ↓
OpenChart/NSE
       ↓
Store in PostgreSQL
       ↓
Read from PostgreSQL
       ↓
Display candlestick chart
       ↓
Calculate EMA9 / EMA20 / RSI / MACD
       ↓
Display indicators
```

Once this works reliably, continue to the simulator.

---

# 80. Second Milestone

Implement:

```text
Historical data
       ↓
Hardcoded EMA strategy
       ↓
BUY / SELL
       ↓
Risk engine
       ↓
Simulated execution
       ↓
Portfolio
       ↓
P&L
       ↓
Trade history
```

At this point the trading system should work **without Gemini**.

---

# 81. Third Milestone

Add Gemini:

```text
Market State
     ↓
Gemini
     ↓
Tool Calls
     ↓
Reasoning
     ↓
Structured Decision
     ↓
Pydantic
     ↓
Risk Engine
     ↓
Simulator
```

Then remove the hardcoded decision layer from the AI-agent mode.

---

# 82. Final End-to-End Target

The finished application should allow:

```text
User
 ↓
Create "Reliance Momentum Agent"
 ↓
RELIANCE
15m
₹1,00,000
2% risk
 ↓
Natural-language strategy
 ↓
Gemini understands mandate
 ↓
User reviews agent
 ↓
Start simulation
 ↓
Historical data loaded from PostgreSQL
 ↓
Market candle arrives
 ↓
Indicators calculated
 ↓
Agent observes environment
 ↓
Agent calls tools
 ↓
Gemini reasons
 ↓
BUY / SELL / HOLD
 ↓
Pydantic validation
 ↓
Risk engine
 ↓
Simulated order
 ↓
Portfolio updated
 ↓
Decision logged
 ↓
Next meaningful event
 ↓
Agent reassesses
 ↓
Simulation completes
 ↓
Performance + agent decisions + trade history
 ↓
Compare against deterministic baseline
```

---

# 83. Final Architecture

```text
                         USER
                           │
                           ▼
                 ┌──────────────────┐
                 │    Next.js UI    │
                 │ TypeScript        │
                 └────────┬─────────┘
                          │
                   REST + WebSocket
                          │
                          ▼
                 ┌──────────────────┐
                 │      FastAPI     │
                 └────────┬─────────┘
                          │
        ┌─────────────────┼──────────────────┐
        │                 │                  │
        ▼                 ▼                  ▼
 Market Data         Quant Engine        Agent Engine
 Service             EMA/RSI/MACD            │
        │                 │                  ▼
        │                 │              Gemini
        │                 │                  │
        │                 │            Function Calls
        │                 │                  │
        └────────┬────────┴──────────────────┘
                 │
                 ▼
          Trading Simulator
                 │
                 ▼
            Risk Engine
                 │
                 ▼
        Portfolio / Orders
                 │
                 ▼
             PostgreSQL
                 ▲
                 │
          Historical OHLCV
                 ▲
                 │
        OpenChart / NSE
                 
        Redis
        ├── Cache
        ├── Temporary State
        └── Rate Limiting
```

---

# 84. Final Technology Stack

### Frontend

```text
Next.js
TypeScript
Tailwind CSS
shadcn/ui
Lightweight Charts
TanStack Query
```

### Backend

```text
Python 3.12+
FastAPI
Pydantic v2
Uvicorn
SQLAlchemy 2.x
Alembic
```

### AI

```text
Google Gemini
google-genai
Function Calling
Structured Outputs
```

### Quantitative

```text
Pandas
NumPy
SciPy
pandas-ta-classic
```

### Data

```text
OpenChart
NSE public charting data
Custom MarketDataProvider
```

### Storage

```text
PostgreSQL
Redis
```

### Communication

```text
REST
Native WebSockets
```

### Testing

```text
pytest
pytest-asyncio
Vitest
```

### Development

```text
uv
Ruff
Pyright
pnpm
ESLint
Prettier
```

### Infrastructure

```text
Docker
Docker Compose
Git
GitHub
```

---

# 85. Definition of Success

The project is successful when a recruiter can sit in front of it and see:

> **"I select RELIANCE, tell the system what kind of trader I want the agent to be, and the system creates an AI trading agent that actually observes the market, uses quantitative tools, reasons about the situation, decides whether to trade, passes through hard risk controls, executes simulated trades, remembers its portfolio state, and lets me analyze whether its decisions were effective."**

That is the project.

**Do not add complexity until this complete loop works.**
