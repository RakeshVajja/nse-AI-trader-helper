"""Safe Tool Execution Harness (Phase 7C).

Provides the trust boundary between untrusted external agent/Gemini input
and the authoritative, deterministic simulation backend.

Enforces:
1. Explicit tool registry (exact 9 Phase 7B tools only).
2. Strict argument validation via Pydantic v2 schemas (extra="forbid").
3. Authoritative context injection (agent cannot supply/override simulation state).
4. Guarded execution of mutating tools (at most one staged order per candle step).
5. Structured error containment mapping all failures to ToolErrorType.
6. Output serialization to pure JSON-compatible dicts via ToolExecutionResult.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel, ValidationError

from app.trading.agent.schemas import (
    CalculatePositionSizeInput,
    CalculatePositionSizeOutput,
    CloseSimulatedPositionInput,
    CloseSimulatedPositionOutput,
    GetIndicatorsInput,
    GetIndicatorsOutput,
    GetMarketDataInput,
    GetMarketDataOutput,
    GetMarketRegimeInput,
    GetMarketRegimeOutput,
    GetPortfolioInput,
    GetPortfolioOutput,
    GetPositionInput,
    GetPositionOutput,
    GetTradeHistoryInput,
    GetTradeHistoryOutput,
    PlaceSimulatedOrderInput,
    PlaceSimulatedOrderOutput,
    ToolErrorType,
    ToolExecutionResult,
)
from app.trading.agent.tools import (
    ToolExecutionContext,
    calculate_position_size,
    close_simulated_position,
    get_indicators,
    get_market_data,
    get_market_regime,
    get_portfolio,
    get_position,
    get_trade_history,
    place_simulated_order,
)

logger = logging.getLogger(__name__)

CORE_TOOL_NAMES = frozenset(
    [
        "get_market_data",
        "get_indicators",
        "get_market_regime",
        "get_position",
        "get_portfolio",
        "get_trade_history",
        "calculate_position_size",
        "place_simulated_order",
        "close_simulated_position",
    ]
)


@dataclass(frozen=True)
class ToolDefinition:
    """Explicit definition of an authorized agent tool."""

    name: str
    input_schema: Type[BaseModel]
    output_schema: Type[BaseModel]
    handler: Callable[[ToolExecutionContext, Any], BaseModel]
    is_mutating: bool = False
    description: str = ""


class ToolRegistry:
    """Authoritative registry mapping tool names to verified specifications and handlers."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register an authorized tool definition."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered in this registry.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Look up tool definition by exact name."""
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        """Return list of all registered tool names."""
        return list(self._tools.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)


def create_default_tool_registry() -> ToolRegistry:
    """Construct the default registry containing exactly the 9 Phase 7B tools."""
    registry = ToolRegistry()

    # 1. get_market_data
    registry.register(
        ToolDefinition(
            name="get_market_data",
            input_schema=GetMarketDataInput,
            output_schema=GetMarketDataOutput,
            handler=get_market_data,
            is_mutating=False,
            description="Return recent completed OHLCV candles, current price, and volume.",
        )
    )

    # 2. get_indicators
    registry.register(
        ToolDefinition(
            name="get_indicators",
            input_schema=GetIndicatorsInput,
            output_schema=GetIndicatorsOutput,
            handler=get_indicators,
            is_mutating=False,
            description="Return technical indicators (EMA9, EMA20, SMA50, RSI14, MACD).",
        )
    )

    # 3. get_market_regime
    registry.register(
        ToolDefinition(
            name="get_market_regime",
            input_schema=GetMarketRegimeInput,
            output_schema=GetMarketRegimeOutput,
            handler=get_market_regime,
            is_mutating=False,
            description="Return trend regime (BULLISH/BEARISH/SIDEWAYS) and volatility regime.",
        )
    )

    # 4. get_position
    registry.register(
        ToolDefinition(
            name="get_position",
            input_schema=GetPositionInput,
            output_schema=GetPositionOutput,
            handler=get_position,
            is_mutating=False,
            description="Return active open position details marked to market at candle Close.",
        )
    )

    # 5. get_portfolio
    registry.register(
        ToolDefinition(
            name="get_portfolio",
            input_schema=GetPortfolioInput,
            output_schema=GetPortfolioOutput,
            handler=get_portfolio,
            is_mutating=False,
            description="Return portfolio accounting metrics, equity, and cash balances.",
        )
    )

    # 6. get_trade_history
    registry.register(
        ToolDefinition(
            name="get_trade_history",
            input_schema=GetTradeHistoryInput,
            output_schema=GetTradeHistoryOutput,
            handler=get_trade_history,
            is_mutating=False,
            description="Return recent completed trades closed on or before current candle.",
        )
    )

    # 7. calculate_position_size
    registry.register(
        ToolDefinition(
            name="calculate_position_size",
            input_schema=CalculatePositionSizeInput,
            output_schema=CalculatePositionSizeOutput,
            handler=calculate_position_size,
            is_mutating=False,
            description="Deterministically calculate safe position size respecting risk limits.",
        )
    )

    # 8. place_simulated_order
    registry.register(
        ToolDefinition(
            name="place_simulated_order",
            input_schema=PlaceSimulatedOrderInput,
            output_schema=PlaceSimulatedOrderOutput,
            handler=place_simulated_order,
            is_mutating=True,
            description="Submit simulated order to RiskEngine and stage for candle t+1 Open fill.",
        )
    )

    # 9. close_simulated_position
    registry.register(
        ToolDefinition(
            name="close_simulated_position",
            input_schema=CloseSimulatedPositionInput,
            output_schema=CloseSimulatedPositionOutput,
            handler=close_simulated_position,
            is_mutating=True,
            description="Submit close request for active position and stage for candle t+1 Open fill.",
        )
    )

    return registry


class SafeToolExecutionHarness:
    """Generic, safe execution harness enforcing the trust boundary for agent tool calls."""

    def __init__(self, registry: Optional[ToolRegistry] = None) -> None:
        self.registry = registry if registry is not None else create_default_tool_registry()

    def dispatch(
        self,
        tool_name: str,
        raw_args: Any,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        """Safely validate, inject context, guard, dispatch, and normalize a tool call."""
        # 1. Authoritative context validation
        if not isinstance(context, ToolExecutionContext):
            return ToolExecutionResult(
                tool_name=str(tool_name) if tool_name is not None else "unknown",
                success=False,
                data=None,
                error="Invalid or missing ToolExecutionContext provided to execution harness.",
                error_type=ToolErrorType.INTERNAL_ERROR,
            )

        # 2. Explicit tool registry lookup
        if not isinstance(tool_name, str) or not tool_name.strip():
            return ToolExecutionResult(
                tool_name=str(tool_name),
                success=False,
                data=None,
                error="Tool name must be a non-empty string.",
                error_type=ToolErrorType.UNKNOWN_TOOL,
            )

        tool = self.registry.get(tool_name.strip())
        if tool is None:
            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                data=None,
                error=f"Tool '{tool_name}' is not registered.",
                error_type=ToolErrorType.UNKNOWN_TOOL,
            )

        # 3. Parse and strictly validate input arguments
        if raw_args is None:
            parsed_args: Dict[str, Any] = {}
        elif isinstance(raw_args, str):
            try:
                loaded = json.loads(raw_args)
                if not isinstance(loaded, dict):
                    return ToolExecutionResult(
                        tool_name=tool.name,
                        success=False,
                        data=None,
                        error=(
                            "Tool arguments JSON string must decode to an object/dict, "
                            f"got {type(loaded).__name__}."
                        ),
                        error_type=ToolErrorType.SCHEMA_ERROR,
                    )
                parsed_args = loaded
            except (json.JSONDecodeError, ValueError) as je:
                return ToolExecutionResult(
                    tool_name=tool.name,
                    success=False,
                    data=None,
                    error=f"Malformed JSON argument string for tool '{tool.name}': {je}",
                    error_type=ToolErrorType.SCHEMA_ERROR,
                )
        elif isinstance(raw_args, dict):
            parsed_args = raw_args
        else:
            return ToolExecutionResult(
                tool_name=tool.name,
                success=False,
                data=None,
                error=f"Tool arguments must be a dictionary/mapping, got {type(raw_args).__name__}.",
                error_type=ToolErrorType.SCHEMA_ERROR,
            )

        try:
            validated_input = tool.input_schema.model_validate(parsed_args)
        except ValidationError as val_err:
            return ToolExecutionResult(
                tool_name=tool.name,
                success=False,
                data=None,
                error=f"Schema validation failed for tool '{tool.name}': {val_err}",
                error_type=ToolErrorType.SCHEMA_ERROR,
            )

        # 4. Context injection & symbol lock verification
        # The agent must not be able to override symbol outside the context instrument
        if hasattr(validated_input, "symbol"):
            sym = validated_input.symbol
            if sym is not None and sym.strip().upper() != context.symbol:
                return ToolExecutionResult(
                    tool_name=tool.name,
                    success=False,
                    data=None,
                    error=(
                        f"Symbol mismatch: tool context is locked to '{context.symbol}', "
                        f"but received '{sym}'."
                    ),
                    error_type=ToolErrorType.STATE_ERROR,
                )

        # 5. Mutating tool staged-order guard (at most one staged order per candle step)
        if tool.is_mutating and any(
            o.decision_time == context.virtual_time for o in context.staged_orders
        ):
            return ToolExecutionResult(
                tool_name=tool.name,
                success=False,
                data=None,
                error="Order already staged for current candle step.",
                error_type=ToolErrorType.ORDER_ALREADY_STAGED,
            )

        # 6. Authorized tool execution with structured exception containment
        try:
            raw_output = tool.handler(context, validated_input)
        except ValueError as ve:
            return ToolExecutionResult(
                tool_name=tool.name,
                success=False,
                data=None,
                error=f"State/validation error in tool '{tool.name}': {ve}",
                error_type=ToolErrorType.STATE_ERROR,
            )
        except Exception as exc:
            logger.exception("Unexpected internal exception executing tool '%s'", tool.name)
            return ToolExecutionResult(
                tool_name=tool.name,
                success=False,
                data=None,
                error=f"Internal error executing tool '{tool.name}': {type(exc).__name__}: {exc}",
                error_type=ToolErrorType.INTERNAL_ERROR,
            )

        # 7. Output schema validation & serialization
        if not isinstance(raw_output, tool.output_schema):
            try:
                validated_output = tool.output_schema.model_validate(raw_output)
            except ValidationError as ve:
                return ToolExecutionResult(
                    tool_name=tool.name,
                    success=False,
                    data=None,
                    error=f"Tool output failed schema validation: {ve}",
                    error_type=ToolErrorType.INTERNAL_ERROR,
                )
        else:
            validated_output = raw_output

        data_dict = validated_output.model_dump(mode="json")

        # 8. Tool-level rejection mapping (e.g. risk rejections or state rejections)
        if hasattr(validated_output, "success") and not validated_output.success:
            reason = (
                getattr(validated_output, "rejection_reason", None) or "Tool operation rejected."
            )
            reason_lower = reason.lower()
            if "already staged" in reason_lower:
                err_type = ToolErrorType.ORDER_ALREADY_STAGED
            elif "risk check failed" in reason_lower:
                err_type = ToolErrorType.RISK_REJECTION
            else:
                err_type = ToolErrorType.STATE_ERROR

            return ToolExecutionResult(
                tool_name=tool.name,
                success=False,
                data=data_dict,
                error=reason,
                error_type=err_type,
            )

        # 9. Clean successful execution
        return ToolExecutionResult(
            tool_name=tool.name,
            success=True,
            data=data_dict,
            error=None,
            error_type=None,
        )

    def execute_tool(
        self,
        context: ToolExecutionContext,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> ToolExecutionResult:
        """Execute tool accepting (context, tool_name, arguments)."""
        return self.dispatch(tool_name=tool_name, raw_args=arguments, context=context)


# Module-level default harness instance
_default_harness = SafeToolExecutionHarness()


def dispatch_tool(
    tool_name: str,
    raw_args: Any,
    context: ToolExecutionContext,
    registry: Optional[ToolRegistry] = None,
) -> ToolExecutionResult:
    """Top-level convenience dispatch matching implementation_plan.md signature."""
    harness = _default_harness if registry is None else SafeToolExecutionHarness(registry=registry)
    return harness.dispatch(tool_name=tool_name, raw_args=raw_args, context=context)


def execute_tool(
    context: ToolExecutionContext,
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
    registry: Optional[ToolRegistry] = None,
) -> ToolExecutionResult:
    """Top-level convenience helper to execute a tool in safe harness."""
    harness = _default_harness if registry is None else SafeToolExecutionHarness(registry=registry)
    return harness.execute_tool(context=context, tool_name=tool_name, arguments=arguments)
