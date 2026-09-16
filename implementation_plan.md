# Implementation Plan: Phase 7 — Agent Tool Layer

## 1. Goal & Scope
Phase 7 implements the typed agent tool layer through which Gemini (in Phase 8) perceives market state, inspects account status, calculates risk-compliant position sizes, and stages simulated trading orders.

Phase 7 comprises four sub-phases:
- **7A:** Pydantic schemas for typed agent tools and structured output (`AgentDecision`).
- **7B:** 9 core agent tools implementation mapping to existing deterministic backend components.
- **7C:** Safe tool execution harness with strict trust boundaries, input validation, context injection, and error containment.
- **7D:** Comprehensive unit tests and schema validation.

Phase 7 preserves all frozen Phase 5 and Phase 6 behavior. Fills remain deferred to candle $t+1$ Open; tools never execute immediate fills at candle $t$ Close.

---

## 2. Frozen Architectural Principles & Boundaries

### 1. Deterministic Environment Supremacy
Gemini operates as an agent inside the existing deterministic trading environment. Gemini must **never** directly modify:
- PostgreSQL database tables
- `PortfolioTracker` state
- `orders` or `trades` tables
- Simulation clock or replay state
- Arbitrary Python or filesystem state

### 2. Strict Typed Tool Boundary
Gemini interacts **exclusively** through explicitly registered, strictly typed tools with Pydantic v2 schemas (`extra="forbid"`, `frozen=True`).

### 3. Separation of Responsibilities (G1 Clarification Frozen)
- **Phase 7 Responsibility:** Typed tool-call validation, execution against deterministic backend components, and staging orders for next-open execution.
- **Order Staging Limit:** `place_simulated_order()` and `close_simulated_position()` may stage at most one order per candle step. Subsequent order calls on the same candle step are rejected with a structured error.
- **No AgentDecision Processing in Phase 7:** Phase 7 MUST NOT interpret, generate, reconcile, or execute `AgentDecision` objects. Phase 7 contains zero `AgentDecision`-specific controller logic.
- **Phase 8 Reconciliation Responsibility:** `AgentDecision`/tool-call reconciliation is exclusively a Phase 8 Gemini agent-loop responsibility.
- **Structured State Exposure:** Phase 7 exposes structured information (e.g. whether an order was staged, the staged `order_id`, and staging status in the execution context and tool execution results) so Phase 8 can determine whether an order was already staged, without Phase 7 containing `AgentDecision` controller logic.

### 4. Zero Arbitrary Execution
There is no path from Gemini-controlled input to arbitrary Python (`eval()`, `exec()`), shell commands, dynamic SQL, or filesystem access. Unknown tools, malformed arguments, or unauthorized operations fail safely and return structured error objects.

---

## 3. Sub-Phase Architecture & Deliverables

### Sub-Phase 7A: Typed Pydantic Schemas & Structured Output
- **Module:** `apps/api/app/trading/agent/schemas.py`
- **Schemas Defined:**
  1. `GetMarketDataInput` & `GetMarketDataOutput`
  2. `GetIndicatorsInput` & `GetIndicatorsOutput`
  3. `GetMarketRegimeInput` & `GetMarketRegimeOutput`
  4. `GetPositionInput` & `GetPositionOutput`
  5. `GetPortfolioInput` & `GetPortfolioOutput`
  6. `GetTradeHistoryInput` & `GetTradeHistoryOutput`
  7. `CalculatePositionSizeInput` & `CalculatePositionSizeOutput`
  8. `PlaceSimulatedOrderInput` & `PlaceSimulatedOrderOutput`
  9. `CloseSimulatedPositionInput` & `CloseSimulatedPositionOutput`
  10. `ToolExecutionResult` (unified envelope: `tool_name`, `success`, `data`, `error`, `error_type`)
  11. `AgentDecision` & `AgentAction` (structured output schema defined per Section 39; not processed by Phase 7 logic)
- **Schema Constraints:**
  - `extra="forbid"`, `frozen=True` across all schemas.
  - Positive quantities (`gt=0`), positive prices (`gt=0.0`), confidence bounds (`0.0 <= confidence <= 1.0`), lookback bounds (`1 <= lookback <= 100`).

### Sub-Phase 7B: 9 Core Agent Tools Implementation
- **Module:** `apps/api/app/trading/agent/tools.py`
- **Context:** Tools receive a frozen `ToolExecutionContext`:
  - `symbol: str` (active simulation instrument)
  - `timeframe: str`
  - `virtual_time: datetime`
  - `current_candle: CandleData` (candle $t$)
  - `visible_candles: Tuple[CandleData, ...]` (candles $0 \dots t$)
  - `portfolio: PortfolioTracker`
  - `risk_engine: RiskEngine`
  - `staged_orders: List[OrderRequest]` (mutable list belonging to active candle step)
- **Tool Mapping:**
  - `get_market_data`: Reads `visible_candles` up to $t$. Read-only.
  - `get_indicators`: Computes indicators using pure functions in `app.indicators.*`. Read-only.
  - `get_market_regime`: Delegates to `classify_market_regime_snapshot(visible_candles)`. Read-only.
  - `get_position`: Reads `portfolio.get_position(symbol)`. Read-only.
  - `get_portfolio`: Reads `portfolio.get_state()`. Read-only.
  - `get_trade_history`: Reads `portfolio.closed_trades[-limit:]`. Read-only.
  - `calculate_position_size`: Pure calculation via `RiskEngine.calculate_position_size()`. Read-only.
  - `place_simulated_order`: Validates order via `RiskEngine.validate_order()`. If approved, stages to `staged_orders` for candle $t+1$ Open fill. Mutating.
  - `close_simulated_position`: Validates close order via `RiskEngine.validate_order()`. Stages to `staged_orders` for candle $t+1$ Open fill. Mutating.

### Sub-Phase 7C: Safe Tool Execution Harness
- **Module:** `apps/api/app/trading/agent/harness.py`
- **Responsibilities:**
  - `ToolRegistry`: Registry mapping registered tool names to tool callable and input/output Pydantic schemas.
  - `dispatch(tool_name, raw_args, context) -> ToolExecutionResult`:
    1. Verify tool registration. If unregistered $\implies$ return structured error (`UNKNOWN_TOOL`).
    2. Parse and validate `raw_args` using tool input Pydantic model. If invalid $\implies$ return structured error (`SCHEMA_ERROR`).
    3. Context Injection: enforce simulation `symbol`, `virtual_time`, and prevent agent override of sandbox parameters.
    4. Guard single staged order per candle bar: if mutating tool called when an order is already staged $\implies$ return structured rejection (`ORDER_ALREADY_STAGED`).
    5. Catch internal exceptions $\implies$ return structured error (`INTERNAL_ERROR`). Never crash simulation.
    6. Return typed `ToolExecutionResult`.

### Sub-Phase 7D: Unit Tests & Schema Validation
- **Modules:**
  - `apps/api/tests/test_agent_schemas.py` (all input/output models, bounds, extra fields, enums)
  - `apps/api/tests/test_agent_tools_readonly.py` (data, indicators, regime, position, portfolio, trades, sizing)
  - `apps/api/tests/test_agent_tools_trading.py` (staging orders, risk engine rejections, cash limits, position closing)
  - `apps/api/tests/test_tool_harness.py` (dispatch, unknown tools, malformed inputs, single-order guard, security isolation)

---

## 4. Verification Plan

### Automated Pytest Suite
```bash
pytest tests/test_agent_schemas.py tests/test_agent_tools_readonly.py tests/test_agent_tools_trading.py tests/test_tool_harness.py -v
pytest tests/ -v  # Full suite regression check
```
- Verify 100% passing tests across all new Phase 7 tests.
- Verify existing 259 backend tests remain fully passing without regressions.
- Verify Ruff lint and format check cleanly on the entire repository.
