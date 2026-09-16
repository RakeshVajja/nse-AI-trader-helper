"""Pydantic schemas for Phase 8C Event-Driven Gemini Decision Cycle.

Enforces:
- model_config = ConfigDict(extra="forbid", frozen=True)
- Strong typing and explicit lifecycle/reconciliation tracking
- Strict immutability and clean domain isolation
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.trading.agent.schemas import AgentAction, AgentDecision


class CycleStatus(str, Enum):
    """Execution status of an agent decision cycle."""

    SUCCESS = "SUCCESS"
    TOOL_ORDER_STAGED = "TOOL_ORDER_STAGED"
    DECISION_ORDER_STAGED = "DECISION_ORDER_STAGED"
    NO_ACTION = "NO_ACTION"
    MAX_TURNS_EXCEEDED = "MAX_TURNS_EXCEEDED"
    GEMINI_ERROR = "GEMINI_ERROR"
    SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"


class CycleToolExecution(BaseModel):
    """Record of a tool execution invoked during the agent decision cycle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str = Field(..., description="Name of the invoked Phase 7 tool")
    arguments: Dict[str, Any] = Field(
        default_factory=dict, description="Arguments passed to the tool"
    )
    success: bool = Field(..., description="Whether the tool execution succeeded")
    data: Optional[Dict[str, Any]] = Field(
        default=None, description="Output payload on successful execution"
    )
    error: Optional[str] = Field(default=None, description="Diagnostic error message on failure")
    error_type: Optional[str] = Field(default=None, description="Categorized error type on failure")
    execution_time_ms: float = Field(
        default=0.0, ge=0.0, description="Tool execution duration in milliseconds"
    )
    staged_order_id: Optional[str] = Field(
        default=None, description="Order ID if tool successfully staged an order"
    )


class DecisionReconciliation(BaseModel):
    """Result of reconciling the final AgentDecision with tool activity from this cycle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: AgentAction = Field(..., description="Decision action (BUY, SELL, HOLD)")
    order_staged: bool = Field(..., description="True if an order was staged for next candle open")
    order_id: Optional[str] = Field(
        default=None, description="Staged order ID if an order was staged"
    )
    order_source: Optional[str] = Field(
        default=None,
        description="Source of staged order: 'TOOL', 'DECISION', or None",
    )
    status: str = Field(
        ...,
        description="Reconciliation status (e.g. 'ALREADY_STAGED_BY_TOOL', 'STAGED_BY_DECISION', 'NO_ORDER_REQUIRED')",
    )
    reconciliation_notes: Optional[str] = Field(
        default=None, description="Explanatory notes regarding reconciliation outcome"
    )


class DecisionCycleResult(BaseModel):
    """Complete outcome of a single simulated completed-candle agent decision cycle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cycle_id: str = Field(..., description="Unique UUID identifier for this cycle")
    agent_id: str = Field(..., description="Identifier of the trading agent")
    simulation_id: Optional[str] = Field(default=None, description="Optional simulation run ID")
    candle_timestamp: datetime = Field(..., description="Timestamp of the completed candle t")
    status: CycleStatus = Field(..., description="Overall cycle execution status")
    decision: Optional[AgentDecision] = Field(
        default=None, description="Validated AgentDecision produced by Gemini"
    )
    reconciliation: Optional[DecisionReconciliation] = Field(
        default=None, description="Reconciliation outcome between decision and tool activity"
    )
    tool_executions: List[CycleToolExecution] = Field(
        default_factory=list, description="Ordered list of tool executions during this cycle"
    )
    orders_staged: List[str] = Field(
        default_factory=list, description="Order IDs staged during this cycle"
    )
    prompt_tokens: int = Field(default=0, ge=0, description="Tokens used for prompt")
    completion_tokens: int = Field(
        default=0, ge=0, description="Tokens used for candidate completions"
    )
    total_tokens: int = Field(default=0, ge=0, description="Total tokens consumed")
    total_latency_ms: float = Field(
        default=0.0, ge=0.0, description="Total cycle latency in milliseconds"
    )
    turns_count: int = Field(default=0, ge=0, description="Number of model turns in loop")
    error: Optional[str] = Field(
        default=None, description="Error message if cycle encountered a failure"
    )
