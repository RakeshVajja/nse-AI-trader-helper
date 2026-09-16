"""Unit and integration tests for database engine, models, and session management."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import models
from app.database.base import Base
from app.database.session import check_db_connection, get_db_session


@pytest.fixture
async def memory_db():
    """Create an in-memory SQLite database with all tables created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_metadata_tables_registered():
    """Verify that all core application tables are registered in Base.metadata."""
    expected_tables = {
        "instruments",
        "candles",
        "market_data_ranges",
        "agents",
        "agent_configs",
        "simulation_runs",
        "agent_decisions",
        "agent_tool_calls",
        "agent_usage",
        "orders",
        "trades",
        "positions",
        "portfolio_snapshots",
    }
    assert expected_tables.issubset(set(Base.metadata.tables.keys()))


@pytest.mark.asyncio
async def test_instrument_and_candles_crud(memory_db: AsyncSession):
    """Verify Instrument creation and nested Candle persistence with foreign key."""
    inst = models.Instrument(
        symbol="RELIANCE",
        name="Reliance Industries Ltd.",
        exchange="NSE",
        instrument_type=models.InstrumentType.EQUITY,
    )
    memory_db.add(inst)
    await memory_db.commit()
    await memory_db.refresh(inst)

    assert inst.id is not None
    assert inst.symbol == "RELIANCE"

    candle_time = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)
    candle = models.Candle(
        instrument_id=inst.id,
        timeframe="15m",
        timestamp=candle_time,
        open=2500.0,
        high=2520.0,
        low=2495.0,
        close=2515.0,
        volume=10500.0,
    )
    memory_db.add(candle)
    await memory_db.commit()

    # Query back
    stmt = select(models.Candle).where(
        models.Candle.instrument_id == inst.id,
        models.Candle.timeframe == "15m",
    )
    res = await memory_db.execute(stmt)
    fetched_candle = res.scalar_one()
    assert fetched_candle.close == 2515.0
    assert fetched_candle.volume == 10500.0


@pytest.mark.asyncio
async def test_candle_unique_constraint(memory_db: AsyncSession):
    """Verify unique constraint on (instrument_id, timeframe, timestamp)."""
    inst = models.Instrument(
        symbol="TCS",
        name="Tata Consultancy Services",
        exchange="NSE",
        instrument_type=models.InstrumentType.EQUITY,
    )
    memory_db.add(inst)
    await memory_db.commit()

    candle_time = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)
    c1 = models.Candle(
        instrument_id=inst.id,
        timeframe="15m",
        timestamp=candle_time,
        open=3800.0,
        high=3820.0,
        low=3790.0,
        close=3810.0,
        volume=5000.0,
    )
    c2 = models.Candle(
        instrument_id=inst.id,
        timeframe="15m",
        timestamp=candle_time,
        open=3805.0,
        high=3825.0,
        low=3795.0,
        close=3815.0,
        volume=6000.0,
    )
    memory_db.add(c1)
    await memory_db.commit()

    memory_db.add(c2)
    with pytest.raises(IntegrityError):
        await memory_db.commit()
    await memory_db.rollback()


@pytest.mark.asyncio
async def test_agent_and_config_creation(memory_db: AsyncSession):
    """Verify Agent and AgentConfig creation with structured JSON fields."""
    inst = models.Instrument(
        symbol="INFY",
        name="Infosys Ltd.",
        exchange="NSE",
        instrument_type=models.InstrumentType.EQUITY,
    )
    memory_db.add(inst)
    await memory_db.commit()

    agent = models.Agent(
        name="Infosys Momentum Agent",
        instrument_id=inst.id,
        timeframe="15m",
        initial_capital=100000.0,
        max_risk_per_trade=0.02,
        max_position_exposure=0.25,
        max_daily_loss=0.05,
        strategy_prompt="Momentum trading with EMA9 and EMA20 crossover",
    )
    memory_db.add(agent)
    await memory_db.commit()
    await memory_db.refresh(agent)

    config = models.AgentConfig(
        agent_id=agent.id,
        strategy_style="momentum",
        objectives=["capture bullish trends", "minimize drawdown"],
        preferred_indicators=["EMA9", "EMA20", "RSI14"],
        raw_mandate={"style": "momentum", "risk": 0.02},
    )
    memory_db.add(config)
    await memory_db.commit()
    await memory_db.refresh(agent)

    # Query back and verify relationship
    stmt = select(models.Agent).where(models.Agent.id == agent.id)
    res = await memory_db.execute(stmt)
    fetched_agent = res.scalar_one()
    assert fetched_agent.name == "Infosys Momentum Agent"
    assert fetched_agent.config is not None
    assert fetched_agent.config.strategy_style == "momentum"
    assert "EMA9" in fetched_agent.config.preferred_indicators


@pytest.mark.asyncio
async def test_simulation_orders_and_trades_flow(memory_db: AsyncSession):
    """Verify SimulationRun, Order, Trade, and PortfolioSnapshot persistence."""
    inst = models.Instrument(
        symbol="SBIN",
        name="State Bank of India",
        exchange="NSE",
        instrument_type=models.InstrumentType.EQUITY,
    )
    memory_db.add(inst)
    await memory_db.commit()

    sim = models.SimulationRun(
        instrument_id=inst.id,
        timeframe="15m",
        start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2025, 1, 31, tzinfo=timezone.utc),
        initial_capital=100000.0,
        status=models.SimulationStatus.RUNNING,
    )
    memory_db.add(sim)
    await memory_db.commit()

    order = models.Order(
        simulation_id=sim.id,
        instrument_id=inst.id,
        order_type=models.OrderType.MARKET,
        side=models.OrderSide.BUY,
        quantity=50,
        price=800.0,
        status=models.OrderStatus.FILLED,
        candle_timestamp=datetime(2025, 1, 15, 9, 30, tzinfo=timezone.utc),
    )
    memory_db.add(order)
    await memory_db.commit()

    trade = models.Trade(
        simulation_id=sim.id,
        order_id=order.id,
        instrument_id=inst.id,
        side=models.OrderSide.BUY,
        quantity=50,
        entry_price=800.0,
        transaction_costs=12.0,
        slippage_cost=20.0,
        entry_time=datetime(2025, 1, 15, 9, 30, tzinfo=timezone.utc),
    )
    memory_db.add(trade)

    snapshot = models.PortfolioSnapshot(
        simulation_id=sim.id,
        timestamp=datetime(2025, 1, 15, 9, 30, tzinfo=timezone.utc),
        cash=60000.0,
        portfolio_value=100000.0,
        gross_pnl=0.0,
        net_pnl=-32.0,
        exposure_pct=0.40,
        open_positions_count=1,
    )
    memory_db.add(snapshot)
    await memory_db.commit()

    # Query back
    stmt = select(models.SimulationRun).where(models.SimulationRun.id == sim.id)
    res = await memory_db.execute(stmt)
    fetched_sim = res.scalar_one()
    assert len(fetched_sim.orders) == 1
    assert len(fetched_sim.trades) == 1
    assert len(fetched_sim.snapshots) == 1
    assert fetched_sim.orders[0].price == 800.0


@pytest.mark.asyncio
async def test_market_data_range_crud_and_constraint(memory_db: AsyncSession):
    """Verify MarketDataRange creation, query, and unique constraint."""
    inst = models.Instrument(
        symbol="WIPRO",
        name="Wipro Ltd.",
        exchange="NSE",
        instrument_type=models.InstrumentType.EQUITY,
    )
    memory_db.add(inst)
    await memory_db.commit()

    range1 = models.MarketDataRange(
        instrument_id=inst.id,
        timeframe="15m",
        earliest_timestamp=datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc),
        latest_timestamp=datetime(2025, 1, 31, 15, 30, tzinfo=timezone.utc),
        total_candles=500,
        last_updated=datetime.now(timezone.utc),
    )
    memory_db.add(range1)
    await memory_db.commit()

    # Query back
    stmt = select(models.MarketDataRange).where(models.MarketDataRange.instrument_id == inst.id)
    res = await memory_db.execute(stmt)
    fetched_range = res.scalar_one()
    assert fetched_range.total_candles == 500
    assert fetched_range.timeframe == "15m"

    # Duplicate constraint
    range2 = models.MarketDataRange(
        instrument_id=inst.id,
        timeframe="15m",
        earliest_timestamp=datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc),
        latest_timestamp=datetime(2025, 1, 31, 15, 30, tzinfo=timezone.utc),
        total_candles=500,
        last_updated=datetime.now(timezone.utc),
    )
    memory_db.add(range2)
    with pytest.raises(IntegrityError):
        await memory_db.commit()
    await memory_db.rollback()


@pytest.mark.asyncio
async def test_agent_decision_tool_call_and_usage_logging(memory_db: AsyncSession):
    """Verify AgentDecision, AgentToolCall, and AgentUsage models."""
    inst = models.Instrument(
        symbol="HDFCBANK",
        name="HDFC Bank Ltd.",
        exchange="NSE",
        instrument_type=models.InstrumentType.EQUITY,
    )
    memory_db.add(inst)
    await memory_db.commit()

    agent = models.Agent(
        name="HDFC Breakout Agent",
        instrument_id=inst.id,
        strategy_prompt="Breakout trading on 15m timeframe",
    )
    memory_db.add(agent)
    await memory_db.commit()

    decision = models.AgentDecision(
        agent_id=agent.id,
        candle_timestamp=datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc),
        action=models.AgentAction.BUY,
        confidence=0.88,
        quantity=25,
        stop_loss=1620.0,
        take_profit=1700.0,
        reason="Bullish engulfing candle with RSI divergence above 50",
        observations=["RSI at 56.4", "EMA9 crossed above EMA20"],
        tools_used=["get_indicators", "check_risk_limits"],
        market_regime="BULLISH",
    )
    memory_db.add(decision)
    await memory_db.commit()

    tool_call = models.AgentToolCall(
        decision_id=decision.id,
        agent_id=agent.id,
        tool_name="get_indicators",
        tool_args={"symbol": "HDFCBANK", "indicators": ["EMA9", "EMA20", "RSI14"]},
        tool_result={"EMA9": 1640.5, "EMA20": 1635.0, "RSI14": 56.4},
        execution_time_ms=12.5,
    )
    usage = models.AgentUsage(
        agent_id=agent.id,
        prompt_tokens=420,
        completion_tokens=85,
        total_tokens=505,
        latency_ms=340.0,
        estimated_cost_usd=0.00021,
    )
    memory_db.add_all([tool_call, usage])
    await memory_db.commit()

    # Query back
    stmt = select(models.Agent).where(models.Agent.id == agent.id)
    res = await memory_db.execute(stmt)
    fetched_agent = res.scalar_one()

    assert len(fetched_agent.decisions) == 1
    assert fetched_agent.decisions[0].action == models.AgentAction.BUY
    assert len(fetched_agent.decisions[0].tool_calls) == 1
    assert fetched_agent.decisions[0].tool_calls[0].tool_name == "get_indicators"
    assert len(fetched_agent.usages) == 1
    assert fetched_agent.usages[0].total_tokens == 505


@pytest.mark.asyncio
async def test_position_tracking_in_simulation(memory_db: AsyncSession):
    """Verify Position tracking entity in simulation run."""
    inst = models.Instrument(
        symbol="ICICIBANK",
        name="ICICI Bank Ltd.",
        exchange="NSE",
        instrument_type=models.InstrumentType.EQUITY,
    )
    memory_db.add(inst)
    await memory_db.commit()

    sim = models.SimulationRun(
        instrument_id=inst.id,
        timeframe="15m",
        start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2025, 1, 31, tzinfo=timezone.utc),
        initial_capital=100000.0,
        status=models.SimulationStatus.RUNNING,
    )
    memory_db.add(sim)
    await memory_db.commit()

    pos = models.Position(
        simulation_id=sim.id,
        instrument_id=inst.id,
        quantity=100,
        average_entry_price=1250.0,
        current_price=1275.0,
        stop_loss=1220.0,
        take_profit=1310.0,
        unrealized_pnl=2500.0,
        is_open=True,
    )
    memory_db.add(pos)
    await memory_db.commit()

    stmt = select(models.SimulationRun).where(models.SimulationRun.id == sim.id)
    res = await memory_db.execute(stmt)
    fetched_sim = res.scalar_one()
    assert len(fetched_sim.positions) == 1
    assert fetched_sim.positions[0].unrealized_pnl == 2500.0
    assert fetched_sim.positions[0].is_open is True


@pytest.mark.asyncio
async def test_get_db_session_dependency():
    """Verify the get_db_session generator yields an AsyncSession."""
    async for session in get_db_session():
        assert isinstance(session, AsyncSession)
        break


@pytest.mark.asyncio
async def test_check_db_connection_graceful_handling():
    """Verify check_db_connection handles unreachable DB without crashing."""
    status = await check_db_connection()
    assert isinstance(status, bool)
