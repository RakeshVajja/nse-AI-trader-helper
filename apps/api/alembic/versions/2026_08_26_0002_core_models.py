"""Create core database models for market data, agents, simulations, orders, and portfolio.

Revision ID: 0002_core_models
Revises: 0001_initial_base
Create Date: 2026-08-26 01:00:00.000000+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_core_models"
down_revision: str | None = "0001_initial_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. instruments
    op.create_table(
        "instruments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("exchange", sa.String(length=10), nullable=False, server_default="NSE"),
        sa.Column("instrument_type", sa.String(length=20), nullable=False, server_default="EQUITY"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol"),
    )
    op.create_index("ix_instruments_symbol", "instruments", ["symbol"])

    # 2. candles
    op.create_table(
        "candles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instrument_id", "timeframe", "timestamp", name="uq_candle_instrument_tf_time"
        ),
    )
    op.create_index("ix_candle_query", "candles", ["instrument_id", "timeframe", "timestamp"])
    op.create_index("ix_candles_instrument_id", "candles", ["instrument_id"])
    op.create_index("ix_candles_timeframe", "candles", ["timeframe"])
    op.create_index("ix_candles_timestamp", "candles", ["timestamp"])

    # 3. market_data_ranges
    op.create_table(
        "market_data_ranges",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("earliest_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latest_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_candles", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instrument_id", "timeframe", name="uq_range_instrument_tf"),
    )
    op.create_index("ix_market_data_ranges_instrument_id", "market_data_ranges", ["instrument_id"])

    # 4. agents
    op.create_table(
        "agents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="CREATED"),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False, server_default="15m"),
        sa.Column("initial_capital", sa.Float(), nullable=False, server_default="100000.0"),
        sa.Column("max_risk_per_trade", sa.Float(), nullable=False, server_default="0.02"),
        sa.Column("max_position_exposure", sa.Float(), nullable=False, server_default="0.25"),
        sa.Column("max_daily_loss", sa.Float(), nullable=False, server_default="0.05"),
        sa.Column("strategy_prompt", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    # 5. agent_configs
    op.create_table(
        "agent_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("strategy_style", sa.String(length=50), nullable=False),
        sa.Column("objectives", sa.JSON(), nullable=False),
        sa.Column("preferred_indicators", sa.JSON(), nullable=False),
        sa.Column("raw_mandate", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id"),
    )

    # 6. simulation_runs
    op.create_table(
        "simulation_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=True),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False, server_default="15m"),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initial_capital", sa.Float(), nullable=False, server_default="100000.0"),
        sa.Column("final_portfolio_value", sa.Float(), nullable=True),
        sa.Column("total_return_pct", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="CREATED"),
        sa.Column("is_baseline", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_simulation_runs_agent_id", "simulation_runs", ["agent_id"])

    # 7. agent_decisions
    op.create_table(
        "agent_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("simulation_id", sa.String(length=36), nullable=True),
        sa.Column("candle_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("stop_loss", sa.Float(), nullable=True),
        sa.Column("take_profit", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("observations", sa.JSON(), nullable=False),
        sa.Column("tools_used", sa.JSON(), nullable=False),
        sa.Column("market_regime", sa.String(length=30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["simulation_id"], ["simulation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_decision_search",
        "agent_decisions",
        ["agent_id", "simulation_id", "candle_timestamp"],
    )
    op.create_index("ix_agent_decisions_agent_id", "agent_decisions", ["agent_id"])
    op.create_index("ix_agent_decisions_simulation_id", "agent_decisions", ["simulation_id"])

    # 8. agent_tool_calls
    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("decision_id", sa.String(length=36), nullable=True),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("tool_name", sa.String(length=50), nullable=False),
        sa.Column("tool_args", sa.JSON(), nullable=False),
        sa.Column("tool_result", sa.JSON(), nullable=False),
        sa.Column("execution_time_ms", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decision_id"], ["agent_decisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_tool_calls_agent_id", "agent_tool_calls", ["agent_id"])
    op.create_index("ix_agent_tool_calls_decision_id", "agent_tool_calls", ["decision_id"])

    # 9. agent_usage
    op.create_table(
        "agent_usage",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("simulation_id", sa.String(length=36), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["simulation_id"], ["simulation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_usage_agent_id", "agent_usage", ["agent_id"])
    op.create_index("ix_agent_usage_simulation_id", "agent_usage", ["simulation_id"])

    # 10. orders
    op.create_table(
        "orders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("simulation_id", sa.String(length=36), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("order_type", sa.String(length=10), nullable=False, server_default="MARKET"),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=15), nullable=False, server_default="PENDING"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("candle_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["simulation_id"], ["simulation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orders_simulation_id", "orders", ["simulation_id"])

    # 11. trades
    op.create_table(
        "trades",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("simulation_id", sa.String(length=36), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=True),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("gross_pnl", sa.Float(), nullable=True),
        sa.Column("net_pnl", sa.Float(), nullable=True),
        sa.Column("transaction_costs", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("slippage_cost", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["simulation_id"], ["simulation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trades_simulation_id", "trades", ["simulation_id"])

    # 12. positions
    op.create_table(
        "positions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("simulation_id", sa.String(length=36), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("average_entry_price", sa.Float(), nullable=False),
        sa.Column("current_price", sa.Float(), nullable=False),
        sa.Column("stop_loss", sa.Float(), nullable=True),
        sa.Column("take_profit", sa.Float(), nullable=True),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("is_open", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["simulation_id"], ["simulation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_positions_simulation_id", "positions", ["simulation_id"])

    # 13. portfolio_snapshots
    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("simulation_id", sa.String(length=36), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("portfolio_value", sa.Float(), nullable=False),
        sa.Column("gross_pnl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("net_pnl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("exposure_pct", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("open_positions_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["simulation_id"], ["simulation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_portfolio_snapshots_simulation_id", "portfolio_snapshots", ["simulation_id"]
    )
    op.create_index("ix_snapshot_sim_time", "portfolio_snapshots", ["simulation_id", "timestamp"])


def downgrade() -> None:
    op.drop_table("portfolio_snapshots")
    op.drop_table("positions")
    op.drop_table("trades")
    op.drop_table("orders")
    op.drop_table("agent_usage")
    op.drop_table("agent_tool_calls")
    op.drop_table("agent_decisions")
    op.drop_table("simulation_runs")
    op.drop_table("agent_configs")
    op.drop_table("agents")
    op.drop_table("market_data_ranges")
    op.drop_table("candles")
    op.drop_table("instruments")
