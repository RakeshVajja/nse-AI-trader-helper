"""Comprehensive CRUD and integration lifecycle tests across all database models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models


@pytest.mark.asyncio
async def test_instrument_candles_and_ranges_lifecycle(db_session: AsyncSession):
    """Verify full CRUD lifecycle and cascade delete on Instrument -> Candles & Ranges."""
    # 1. Create Instrument
    inst = models.Instrument(
        symbol="TATASTEEL",
        name="Tata Steel Limited",
        exchange="NSE",
        instrument_type=models.InstrumentType.EQUITY,
    )
    db_session.add(inst)
    await db_session.commit()
    await db_session.refresh(inst)

    assert inst.id is not None

    from datetime import timedelta

    # 2. Bulk insert Candles
    base_time = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)
    candles = [
        models.Candle(
            instrument_id=inst.id,
            timeframe="15m",
            timestamp=base_time + timedelta(minutes=15 * i),
            open=140.0 + i,
            high=142.0 + i,
            low=139.0 + i,
            close=141.0 + i,
            volume=50000.0,
        )
        for i in range(5)
    ]
    db_session.add_all(candles)

    # 3. Add MarketDataRange
    data_range = models.MarketDataRange(
        instrument_id=inst.id,
        timeframe="15m",
        earliest_timestamp=base_time,
        latest_timestamp=base_time + timedelta(minutes=60),
        total_candles=5,
        last_updated=datetime.now(timezone.utc),
    )
    db_session.add(data_range)
    await db_session.commit()

    # 4. Query with aggregation
    count_stmt = select(func.count(models.Candle.id)).where(models.Candle.instrument_id == inst.id)
    candle_count = (await db_session.execute(count_stmt)).scalar()
    assert candle_count == 5

    # 5. Update Instrument
    inst.name = "Tata Steel Ltd."
    await db_session.commit()
    await db_session.refresh(inst)
    assert inst.name == "Tata Steel Ltd."

    # 6. Delete Instrument and verify cascade delete of Candles and DataRanges
    await db_session.delete(inst)
    await db_session.commit()

    remaining_candles = (
        (
            await db_session.execute(
                select(models.Candle).where(models.Candle.instrument_id == inst.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(remaining_candles) == 0

    remaining_ranges = (
        (
            await db_session.execute(
                select(models.MarketDataRange).where(
                    models.MarketDataRange.instrument_id == inst.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(remaining_ranges) == 0


@pytest.mark.asyncio
async def test_agent_cascade_lifecycle(db_session: AsyncSession):
    """Verify Agent creation, decision logging, tool call logging, usage metrics, and cascade deletion."""
    inst = models.Instrument(
        symbol="BAJFINANCE",
        name="Bajaj Finance Ltd.",
        exchange="NSE",
        instrument_type=models.InstrumentType.EQUITY,
    )
    db_session.add(inst)
    await db_session.commit()

    agent = models.Agent(
        name="Bajaj Mean Reversion",
        instrument_id=inst.id,
        timeframe="15m",
        initial_capital=500000.0,
        strategy_prompt="Mean reversion using RSI and Bollinger Bands",
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    config = models.AgentConfig(
        agent_id=agent.id,
        strategy_style="mean_reversion",
        objectives=["trade oversold bounces"],
        preferred_indicators=["RSI14", "SMA20"],
        raw_mandate={"style": "mean_reversion"},
    )
    decision = models.AgentDecision(
        agent_id=agent.id,
        candle_timestamp=datetime(2025, 2, 1, 11, 0, tzinfo=timezone.utc),
        action=models.AgentAction.BUY,
        confidence=0.92,
        quantity=10,
        stop_loss=6500.0,
        take_profit=7000.0,
        reason="RSI touched 28 oversold level",
        observations=["RSI 28.1", "Lower BB touched"],
        tools_used=["get_indicators"],
        market_regime="SIDEWAYS",
    )
    db_session.add_all([config, decision])
    await db_session.commit()

    tool_call = models.AgentToolCall(
        decision_id=decision.id,
        agent_id=agent.id,
        tool_name="get_indicators",
        tool_args={"indicators": ["RSI14"]},
        tool_result={"RSI14": 28.1},
        execution_time_ms=10.0,
    )
    usage = models.AgentUsage(
        agent_id=agent.id,
        prompt_tokens=300,
        completion_tokens=50,
        total_tokens=350,
        latency_ms=250.0,
        estimated_cost_usd=0.00015,
    )
    db_session.add_all([tool_call, usage])
    await db_session.commit()

    # Verify relationships
    await db_session.refresh(agent)
    await db_session.refresh(decision)
    assert agent.config is not None
    assert len(agent.decisions) == 1
    assert len(agent.usages) == 1
    assert len(decision.tool_calls) == 1

    # Delete agent and verify cascade
    await db_session.delete(agent)
    await db_session.commit()

    configs = (
        (
            await db_session.execute(
                select(models.AgentConfig).where(models.AgentConfig.agent_id == agent.id)
            )
        )
        .scalars()
        .all()
    )
    decisions = (
        (
            await db_session.execute(
                select(models.AgentDecision).where(models.AgentDecision.agent_id == agent.id)
            )
        )
        .scalars()
        .all()
    )
    usages = (
        (
            await db_session.execute(
                select(models.AgentUsage).where(models.AgentUsage.agent_id == agent.id)
            )
        )
        .scalars()
        .all()
    )
    tool_calls = (
        (
            await db_session.execute(
                select(models.AgentToolCall).where(models.AgentToolCall.agent_id == agent.id)
            )
        )
        .scalars()
        .all()
    )

    assert len(configs) == 0
    assert len(decisions) == 0
    assert len(usages) == 0
    assert len(tool_calls) == 0


@pytest.mark.asyncio
async def test_simulation_execution_and_reporting_lifecycle(db_session: AsyncSession):
    """Verify SimulationRun with Orders, Trades, Positions, and PortfolioSnapshots."""
    inst = models.Instrument(
        symbol="KOTAKBANK",
        name="Kotak Mahindra Bank",
        exchange="NSE",
        instrument_type=models.InstrumentType.EQUITY,
    )
    db_session.add(inst)
    await db_session.commit()

    sim = models.SimulationRun(
        instrument_id=inst.id,
        timeframe="15m",
        start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2025, 1, 31, tzinfo=timezone.utc),
        initial_capital=200000.0,
        status=models.SimulationStatus.RUNNING,
    )
    db_session.add(sim)
    await db_session.commit()

    # Record Buy Order & Trade
    order_buy = models.Order(
        simulation_id=sim.id,
        instrument_id=inst.id,
        order_type=models.OrderType.MARKET,
        side=models.OrderSide.BUY,
        quantity=100,
        price=1800.0,
        status=models.OrderStatus.FILLED,
        candle_timestamp=datetime(2025, 1, 5, 9, 30, tzinfo=timezone.utc),
    )
    db_session.add(order_buy)
    await db_session.commit()

    trade_buy = models.Trade(
        simulation_id=sim.id,
        order_id=order_buy.id,
        instrument_id=inst.id,
        side=models.OrderSide.BUY,
        quantity=100,
        entry_price=1800.0,
        transaction_costs=25.0,
        slippage_cost=45.0,
        entry_time=datetime(2025, 1, 5, 9, 30, tzinfo=timezone.utc),
    )
    position = models.Position(
        simulation_id=sim.id,
        instrument_id=inst.id,
        quantity=100,
        average_entry_price=1800.0,
        current_price=1850.0,
        unrealized_pnl=5000.0,
        is_open=True,
    )
    snapshot = models.PortfolioSnapshot(
        simulation_id=sim.id,
        timestamp=datetime(2025, 1, 5, 9, 30, tzinfo=timezone.utc),
        cash=20000.0,
        portfolio_value=205000.0,
        gross_pnl=5000.0,
        net_pnl=4930.0,
        exposure_pct=0.90,
        open_positions_count=1,
    )
    db_session.add_all([trade_buy, position, snapshot])
    await db_session.commit()

    # Complete simulation
    sim.status = models.SimulationStatus.COMPLETED
    sim.final_portfolio_value = 215000.0
    sim.total_return_pct = 7.5
    sim.metrics = {"win_rate": 0.65, "profit_factor": 1.8, "max_drawdown": 0.03}
    await db_session.commit()

    # Verify simulation query
    stmt = select(models.SimulationRun).where(models.SimulationRun.id == sim.id)
    fetched_sim = (await db_session.execute(stmt)).scalar_one()
    assert fetched_sim.status == models.SimulationStatus.COMPLETED
    assert fetched_sim.total_return_pct == 7.5
    assert len(fetched_sim.orders) == 1
    assert len(fetched_sim.trades) == 1
    assert len(fetched_sim.positions) == 1
    assert len(fetched_sim.snapshots) == 1

    # Verify simulation delete cascade
    await db_session.delete(fetched_sim)
    await db_session.commit()

    remaining_orders = (
        (await db_session.execute(select(models.Order).where(models.Order.simulation_id == sim.id)))
        .scalars()
        .all()
    )
    assert len(remaining_orders) == 0


@pytest.mark.asyncio
async def test_transaction_rollback_preserves_clean_state(db_session: AsyncSession):
    """Verify that a rolled-back transaction does not persist partial records."""
    inst = models.Instrument(
        symbol="NESTLEIND",
        name="Nestle India Ltd.",
        exchange="NSE",
        instrument_type=models.InstrumentType.EQUITY,
    )
    db_session.add(inst)
    await db_session.commit()

    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            # Attempt to add duplicate instrument symbol
            dup = models.Instrument(
                symbol="NESTLEIND",
                name="Duplicate Nestle",
                exchange="NSE",
            )
            db_session.add(dup)
            await db_session.flush()

    # Verify original record remains and no corrupted state
    stmt = select(models.Instrument).where(models.Instrument.symbol == "NESTLEIND")
    res = await db_session.execute(stmt)
    records = res.scalars().all()
    assert len(records) == 1
    assert records[0].name == "Nestle India Ltd."
