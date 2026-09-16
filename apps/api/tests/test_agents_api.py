"""Comprehensive Test Suite for Phase 9C: Agent Management API Endpoints.

Validates all 9C endpoints:
- POST /api/v1/agents/mandate (mandate compilation from natural language)
- POST /api/v1/agents (agent confirmation, atomic persistence, duplicate prevention)
- GET /api/v1/agents (paginated list with status filter)
- GET /api/v1/agents/{id} (authoritative agent retrieval)
- GET /api/v1/agents/{id}/status (authoritative status)
- PATCH /api/v1/agents/{id} (metadata updates with immutability enforcement)
- POST /api/v1/agents/{id}/start (lifecycle RUNNING)
- POST /api/v1/agents/{id}/pause (lifecycle PAUSED)
- POST /api/v1/agents/{id}/resume (lifecycle RUNNING)
- POST /api/v1/agents/{id}/stop (lifecycle COMPLETED)
- DELETE /api/v1/agents/{id} (deletion & cascade)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.agents import get_gemini_client, get_simulation_service_dep
from app.database import models
from app.database.base import Base
from app.database.models.agent import Agent, AgentConfig, AgentStatus
from app.database.models.trading import SimulationRun, SimulationStatus
from app.database.session import get_db_session
from app.main import app
from app.trading.agent.gemini import (
    GeminiClient,
    GeminiConfig,
    GeminiErrorType,
    GeminiResponse,
)
from app.trading.simulation.service import SimulationService

SAMPLE_VALID_MANDATE_JSON = """{
  "strategy_style": "momentum",
  "objectives": [
    "capture bullish momentum",
    "avoid choppy periods"
  ],
  "preferred_indicators": [
    "EMA9",
    "EMA20",
    "RSI14",
    "MACD"
  ],
  "instrument": "RELIANCE",
  "timeframe": "15m",
  "risk_per_trade": 0.02,
  "max_position_exposure": 0.25,
  "max_daily_loss": 0.05,
  "rationale": "Translated user momentum strategy prioritizing trend-following with RSI confirmation."
}"""


def create_fake_gemini_client(
    raw_text: str,
    success: bool = True,
    error: str | None = None,
    error_type: GeminiErrorType | None = None,
    prompt_tokens: int = 120,
    completion_tokens: int = 60,
    total_tokens: int = 180,
) -> GeminiClient:
    """Create a mock GeminiClient returning the specified response."""
    gemini_resp = GeminiResponse(
        success=success,
        raw_text=raw_text if success else None,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=35.0,
        error=error,
        error_type=error_type,
    )

    class MockGeminiClient(GeminiClient):
        def __init__(self) -> None:
            super().__init__(config=GeminiConfig(api_key="mock-api-key-test-value"))

        def generate(self, request: Any) -> GeminiResponse:
            return gemini_resp

        async def generate_async(self, request: Any) -> GeminiResponse:
            return gemini_resp

    return MockGeminiClient()


@pytest.fixture
async def agents_test_env():
    """Setup isolated in-memory database and test AsyncClient."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed baseline instrument
    async with session_factory() as db:
        inst = models.Instrument(
            symbol="RELIANCE",
            name="Reliance Industries Limited",
            exchange="NSE",
            instrument_type=models.InstrumentType.EQUITY,
            is_active=True,
        )
        db.add(inst)
        await db.commit()
        await db.refresh(inst)

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    fake_client = create_fake_gemini_client(SAMPLE_VALID_MANDATE_JSON)
    sim_service = SimulationService()
    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_gemini_client] = lambda: fake_client
    app.dependency_overrides[get_simulation_service_dep] = lambda: sim_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield {
            "client": client,
            "session_factory": session_factory,
            "fake_gemini_client": fake_client,
            "sim_service": sim_service,
        }

    app.dependency_overrides.clear()
    await engine.dispose()


# ==============================================================================
# 1. Mandate Generation Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_generate_mandate_success(agents_test_env):
    """POST /api/v1/agents/mandate returns 200 with valid AgentMandateResponse."""
    client: AsyncClient = agents_test_env["client"]

    payload = {
        "agent_name": "MomentumAlpha",
        "strategy_prompt": "Buy when EMA9 crosses above EMA20 and RSI14 is above 50.",
        "instrument": "RELIANCE",
        "timeframe": "15m",
        "initial_capital": 100000.0,
        "max_risk_per_trade": 0.02,
        "max_position_exposure": 0.25,
        "max_daily_loss": 0.05,
    }

    res = await client.post("/api/v1/agents/mandate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["mandate"] is not None
    assert data["mandate"]["strategy_style"] == "momentum"
    assert data["mandate"]["instrument"] == "RELIANCE"
    assert "EMA9" in data["mandate"]["preferred_indicators"]
    assert data["prompt_tokens"] == 120
    assert data["total_tokens"] == 180


@pytest.mark.asyncio
async def test_generate_mandate_invalid_input_rejected(agents_test_env):
    """POST /api/v1/agents/mandate rejects empty prompt or invalid numeric fields."""
    client: AsyncClient = agents_test_env["client"]

    # Short prompt (< 3 chars)
    payload_short = {
        "agent_name": "Alpha",
        "strategy_prompt": "ab",
    }
    res = await client.post("/api/v1/agents/mandate", json=payload_short)
    assert res.status_code == 422

    # Negative capital
    payload_neg = {
        "agent_name": "Alpha",
        "strategy_prompt": "Valid long prompt for strategy",
        "initial_capital": -500.0,
    }
    res = await client.post("/api/v1/agents/mandate", json=payload_neg)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_generate_mandate_failure_converted_to_400(agents_test_env):
    """When LLM generation fails, API converts it to a clean 400 Bad Request."""
    client: AsyncClient = agents_test_env["client"]

    failing_client = create_fake_gemini_client(
        raw_text="",
        success=False,
        error="LLM quota exceeded or model unresponsive",
        error_type=GeminiErrorType.API_ERROR,
    )
    app.dependency_overrides[get_gemini_client] = lambda: failing_client

    payload = {
        "agent_name": "QuotaFailAgent",
        "strategy_prompt": "Buy on breakout above swing high with high volume",
    }
    res = await client.post("/api/v1/agents/mandate", json=payload)
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "LLM quota exceeded" in detail or "Failed" in detail


@pytest.mark.asyncio
async def test_generate_mandate_no_private_keys_or_secrets_exposed(agents_test_env):
    """Ensures responses never leak internal api keys or secret credentials."""
    client: AsyncClient = agents_test_env["client"]

    payload = {
        "agent_name": "SecurityAuditAgent",
        "strategy_prompt": "Trend following strategy using EMA and RSI indicators.",
    }
    res = await client.post("/api/v1/agents/mandate", json=payload)
    assert res.status_code == 200
    response_text = res.text
    assert "mock-api-key-test-value" not in response_text
    assert "GEMINI_API_KEY" not in response_text


@pytest.mark.asyncio
async def test_generate_mandate_delegates_to_8b_service(agents_test_env):
    """Verifies that mandate generation endpoint directly delegates to generate_mandate_async."""
    client: AsyncClient = agents_test_env["client"]

    from app.trading.agent.mandate.generator import generate_mandate_async

    with patch(
        "app.api.v1.agents.generate_mandate_async",
        wraps=generate_mandate_async,
    ) as mock_gen:
        payload = {
            "agent_name": "DelegationCheckAgent",
            "strategy_prompt": "Trend following momentum strategy with EMA9 and EMA20.",
        }
        res = await client.post("/api/v1/agents/mandate", json=payload)
        assert res.status_code == 200
        assert mock_gen.call_count == 1
        # Inspect args passed to 8B service
        called_args, _ = mock_gen.call_args
        assert called_args[1].agent_name == "DelegationCheckAgent"


@pytest.mark.asyncio
async def test_generate_mandate_internal_exception_converted_to_500(agents_test_env):
    """When an unexpected exception occurs during generation, returns clean 500 without leaking traces."""
    client: AsyncClient = agents_test_env["client"]

    with patch(
        "app.api.v1.agents.generate_mandate_async",
        side_effect=RuntimeError("Secret database or internal socket crash: /secret/path/to/key"),
    ):
        payload = {
            "agent_name": "CrashTestAgent",
            "strategy_prompt": "Standard momentum prompt.",
        }
        res = await client.post("/api/v1/agents/mandate", json=payload)
        assert res.status_code == 500
        detail = res.json()["detail"]
        assert "internal server error" in detail.lower()
        # Verify secret internal path is not exposed
        assert "/secret/path/to/key" not in res.text


# ==============================================================================
# 2. Confirmation / Agent Creation Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_create_agent_success(agents_test_env):
    """POST /api/v1/agents creates Agent + AgentConfig atomically and returns 201."""
    client: AsyncClient = agents_test_env["client"]
    session_factory = agents_test_env["session_factory"]

    payload = {
        "agent_name": "BreakoutSniper",
        "initial_capital": 200000.0,
        "mandate": {
            "strategy_style": "breakout",
            "objectives": ["Identify 20-candle resistance breakout"],
            "preferred_indicators": ["EMA20", "RSI14", "ATR14"],
            "instrument": "RELIANCE",
            "timeframe": "15m",
            "risk_per_trade": 0.015,
            "max_position_exposure": 0.20,
            "max_daily_loss": 0.04,
            "rationale": "Aggressive momentum breakout strategy.",
        },
    }

    res = await client.post("/api/v1/agents", json=payload)
    assert res.status_code == 201
    data = res.json()

    # Verify frontend contract compliance
    assert "agent_id" in data
    assert "id" in data
    assert data["agent_id"] == data["id"]
    assert data["name"] == "BreakoutSniper"
    assert data["status"] == "READY"
    assert data["instrument"] == "RELIANCE"
    assert data["timeframe"] == "15m"
    assert data["initial_capital"] == 200000.0
    assert data["max_risk_per_trade"] == 0.015
    assert data["strategy_style"] == "breakout"
    assert "EMA20" in data["preferred_indicators"]
    assert data["message"] == "Agent confirmed and initialized successfully."

    # Verify DB persistence
    agent_id = data["agent_id"]
    async with session_factory() as db:
        agent_stmt = select(Agent).where(Agent.id == agent_id)
        agent_res = await db.execute(agent_stmt)
        agent = agent_res.scalar_one_or_none()
        assert agent is not None
        assert agent.status == AgentStatus.READY
        assert agent.config is not None
        assert agent.config.strategy_style == "breakout"
        assert "EMA20" in agent.config.preferred_indicators


@pytest.mark.asyncio
async def test_create_agent_duplicate_active_name_conflict(agents_test_env):
    """POST /api/v1/agents returns 409 Conflict if an active agent with the same name exists."""
    client: AsyncClient = agents_test_env["client"]

    payload = {
        "agent_name": "UniqueAgentName",
        "initial_capital": 100000.0,
        "mandate": {
            "strategy_style": "momentum",
            "objectives": ["Capture trends"],
            "preferred_indicators": ["EMA9", "EMA20"],
            "instrument": "RELIANCE",
            "timeframe": "15m",
            "risk_per_trade": 0.02,
            "max_position_exposure": 0.25,
            "max_daily_loss": 0.05,
        },
    }

    # First creation succeeds
    res1 = await client.post("/api/v1/agents", json=payload)
    assert res1.status_code == 201

    # Second creation with identical active name returns 409
    res2 = await client.post("/api/v1/agents", json=payload)
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"]


@pytest.mark.asyncio
async def test_create_agent_nested_mandate_validation(agents_test_env):
    """POST /api/v1/agents enforces nested AgentMandate schema constraints."""
    client: AsyncClient = agents_test_env["client"]

    # Unsupported indicator
    payload_bad_ind = {
        "agent_name": "BadIndicatorAgent",
        "initial_capital": 100000.0,
        "mandate": {
            "strategy_style": "momentum",
            "objectives": ["Objective 1"],
            "preferred_indicators": ["BOLLINGER_BANDS"],  # Not supported
            "instrument": "RELIANCE",
            "timeframe": "15m",
            "risk_per_trade": 0.02,
            "max_position_exposure": 0.25,
            "max_daily_loss": 0.05,
        },
    }
    res = await client.post("/api/v1/agents", json=payload_bad_ind)
    assert res.status_code == 422

    # Excessive risk (> 10%)
    payload_bad_risk = {
        "agent_name": "ExcessiveRiskAgent",
        "initial_capital": 100000.0,
        "mandate": {
            "strategy_style": "momentum",
            "objectives": ["Objective 1"],
            "preferred_indicators": ["EMA9"],
            "instrument": "RELIANCE",
            "timeframe": "15m",
            "risk_per_trade": 0.50,  # Max allowed is 0.10
            "max_position_exposure": 0.25,
            "max_daily_loss": 0.05,
        },
    }
    res2 = await client.post("/api/v1/agents", json=payload_bad_risk)
    assert res2.status_code == 422


@pytest.mark.asyncio
async def test_create_agent_transactional_rollback_on_failure(agents_test_env):
    """If downstream operation fails during creation, entire transaction is rolled back."""
    client: AsyncClient = agents_test_env["client"]
    session_factory = agents_test_env["session_factory"]

    payload = {
        "agent_name": "RollbackTestAgent",
        "initial_capital": 100000.0,
        "mandate": {
            "strategy_style": "mean_reversion",
            "objectives": ["Buy oversold dips"],
            "preferred_indicators": ["RSI14"],
            "instrument": "RELIANCE",
            "timeframe": "15m",
            "risk_per_trade": 0.02,
            "max_position_exposure": 0.25,
            "max_daily_loss": 0.05,
        },
    }

    # Simulate failure during AgentConfig initialization by patching flush/commit
    with patch(
        "app.api.v1.agents.AgentConfig",
        side_effect=RuntimeError("Simulated database failure during config instantiation"),
    ):
        res = await client.post("/api/v1/agents", json=payload)
        assert res.status_code == 500

    # Verify no phantom Agent was committed
    async with session_factory() as db:
        stmt = select(Agent).where(Agent.name == "RollbackTestAgent")
        result = await db.execute(stmt)
        assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_create_agent_with_simulation_association(agents_test_env):
    """POST /api/v1/agents correctly links with existing simulation if simulation_id is passed."""
    client: AsyncClient = agents_test_env["client"]
    session_factory = agents_test_env["session_factory"]

    # 1. Create a historical simulation run in DB
    sim_id = "sim-assoc-test-12345"
    async with session_factory() as db:
        inst_stmt = select(models.Instrument).where(models.Instrument.symbol == "RELIANCE")
        inst_res = await db.execute(inst_stmt)
        inst = inst_res.scalar_one()

        sim = SimulationRun(
            id=sim_id,
            instrument_id=inst.id,
            timeframe="15m",
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
            initial_capital=100000.0,
            status=SimulationStatus.CREATED,
            is_baseline=False,
        )
        db.add(sim)
        await db.commit()

    # 2. Confirm agent with simulation_id
    payload = {
        "agent_name": "SimLinkedAgent",
        "initial_capital": 100000.0,
        "simulation_id": sim_id,
        "mandate": {
            "strategy_style": "trend_following",
            "objectives": ["Ride strong daily trends"],
            "preferred_indicators": ["EMA9", "EMA20", "ATR14"],
            "instrument": "RELIANCE",
            "timeframe": "15m",
            "risk_per_trade": 0.02,
            "max_position_exposure": 0.25,
            "max_daily_loss": 0.05,
        },
    }

    res = await client.post("/api/v1/agents", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["simulation_id"] == sim_id
    agent_id = data["agent_id"]

    # 3. Verify simulation_runs.agent_id is updated
    async with session_factory() as db:
        sim_check = await db.execute(select(SimulationRun).where(SimulationRun.id == sim_id))
        sim_record = sim_check.scalar_one()
        assert sim_record.agent_id == agent_id

    # 4. Attempting to link to nonexistent simulation returns 404
    payload_bad_sim = dict(payload)
    payload_bad_sim["agent_name"] = "BadSimAgent"
    payload_bad_sim["simulation_id"] = "nonexistent-sim-999"
    res_bad = await client.post("/api/v1/agents", json=payload_bad_sim)
    assert res_bad.status_code == 404


# ==============================================================================
# 3. Retrieval & Management Tests
# ==============================================================================


@pytest.fixture
async def seeded_agent(agents_test_env):
    """Seed a test agent in READY state."""
    session_factory = agents_test_env["session_factory"]
    async with session_factory() as db:
        inst = (
            await db.execute(
                select(models.Instrument).where(models.Instrument.symbol == "RELIANCE")
            )
        ).scalar_one()

        agent = Agent(
            id="agent-seeded-001",
            name="SeededAlpha",
            description="Seeded test agent",
            status=AgentStatus.READY,
            instrument_id=inst.id,
            timeframe="15m",
            initial_capital=100000.0,
            max_risk_per_trade=0.02,
            max_position_exposure=0.25,
            max_daily_loss=0.05,
            strategy_prompt="Seeded strategy prompt",
        )
        db.add(agent)
        await db.flush()

        config = AgentConfig(
            agent_id=agent.id,
            strategy_style="momentum",
            objectives=["Target bullish trends"],
            preferred_indicators=["EMA9", "EMA20"],
            raw_mandate={
                "strategy_style": "momentum",
                "objectives": ["Target bullish trends"],
                "preferred_indicators": ["EMA9", "EMA20"],
                "instrument": "RELIANCE",
                "timeframe": "15m",
                "risk_per_trade": 0.02,
                "max_position_exposure": 0.25,
                "max_daily_loss": 0.05,
                "rationale": "Seeded test agent rationale",
            },
        )
        db.add(config)
        await db.commit()
        await db.refresh(agent)
        return agent.id


@pytest.mark.asyncio
async def test_get_agent_by_id(agents_test_env, seeded_agent):
    """GET /api/v1/agents/{id} returns authoritative agent configuration."""
    client: AsyncClient = agents_test_env["client"]

    res = await client.get(f"/api/v1/agents/{seeded_agent}")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == seeded_agent
    assert data["name"] == "SeededAlpha"
    assert data["status"] == "READY"
    assert data["instrument"] == "RELIANCE"
    assert data["strategy_style"] == "momentum"
    assert "EMA9" in data["preferred_indicators"]


@pytest.mark.asyncio
async def test_get_agent_not_found(agents_test_env):
    """GET /api/v1/agents/{id} returns 404 for nonexistent agent."""
    client: AsyncClient = agents_test_env["client"]

    res = await client.get("/api/v1/agents/nonexistent-agent-id-999")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_agent_status(agents_test_env, seeded_agent):
    """GET /api/v1/agents/{id}/status returns authoritative lifecycle status."""
    client: AsyncClient = agents_test_env["client"]

    res = await client.get(f"/api/v1/agents/{seeded_agent}/status")
    assert res.status_code == 200
    data = res.json()
    assert data["agent_id"] == seeded_agent
    assert data["name"] == "SeededAlpha"
    assert data["status"] == "READY"
    assert data["instrument"] == "RELIANCE"


@pytest.mark.asyncio
async def test_list_agents(agents_test_env, seeded_agent):
    """GET /api/v1/agents returns paginated agent list and supports status filtering."""
    client: AsyncClient = agents_test_env["client"]

    # 1. Unfiltered list
    res = await client.get("/api/v1/agents")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert data["count"] >= 1
    assert any(a["id"] == seeded_agent for a in data["agents"])

    # 2. Filter by status READY
    res_ready = await client.get("/api/v1/agents?status=READY")
    assert res_ready.status_code == 200
    data_ready = res_ready.json()
    assert all(a["status"] == "READY" for a in data_ready["agents"])

    # 3. Filter by status COMPLETED (none seeded)
    res_comp = await client.get("/api/v1/agents?status=COMPLETED")
    assert res_comp.status_code == 200
    data_comp = res_comp.json()
    assert data_comp["total"] == 0
    assert len(data_comp["agents"]) == 0


@pytest.mark.asyncio
async def test_update_agent_metadata(agents_test_env, seeded_agent):
    """PATCH /api/v1/agents/{id} updates mutable metadata and enforces immutability."""
    client: AsyncClient = agents_test_env["client"]

    # 1. Valid update
    update_payload = {
        "name": "RenamedAlpha",
        "description": "Updated agent description for tests",
    }
    res = await client.patch(f"/api/v1/agents/{seeded_agent}", json=update_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "RenamedAlpha"
    assert data["rationale"] == "Updated agent description for tests"
    assert data["message"] == "Agent updated successfully."

    # 2. Attempting to update immutable fields is rejected with 422
    forbidden_payload = {"risk_per_trade": 0.05}
    res_forbidden = await client.patch(f"/api/v1/agents/{seeded_agent}", json=forbidden_payload)
    assert res_forbidden.status_code == 422

    # 3. Name conflict on update returns 409
    # First create another agent
    res_create = await client.post(
        "/api/v1/agents",
        json={
            "agent_name": "SecondAgent",
            "initial_capital": 100000.0,
            "mandate": {
                "strategy_style": "momentum",
                "objectives": ["Goal"],
                "preferred_indicators": ["EMA9"],
                "instrument": "RELIANCE",
                "timeframe": "15m",
                "risk_per_trade": 0.02,
                "max_position_exposure": 0.25,
                "max_daily_loss": 0.05,
            },
        },
    )
    assert res_create.status_code == 201

    # Try renaming seeded agent to SecondAgent
    res_conflict = await client.patch(
        f"/api/v1/agents/{seeded_agent}",
        json={"name": "SecondAgent"},
    )
    assert res_conflict.status_code == 409


@pytest.mark.asyncio
async def test_agent_lifecycle_transitions(agents_test_env, seeded_agent):
    """Validates start, pause, resume, stop lifecycle state transitions and guards."""
    client: AsyncClient = agents_test_env["client"]

    # 1. Start agent (READY -> RUNNING)
    res_start = await client.post(f"/api/v1/agents/{seeded_agent}/start")
    assert res_start.status_code == 200
    assert res_start.json()["status"] == "RUNNING"

    # Invalid resume while already RUNNING (must be PAUSED)
    res_bad_resume = await client.post(f"/api/v1/agents/{seeded_agent}/resume")
    assert res_bad_resume.status_code == 400
    assert "not paused" in res_bad_resume.json()["detail"].lower()

    # 2. Pause agent (RUNNING -> PAUSED)
    res_pause = await client.post(f"/api/v1/agents/{seeded_agent}/pause")
    assert res_pause.status_code == 200
    assert res_pause.json()["status"] == "PAUSED"

    # Invalid pause while already PAUSED
    res_bad_pause = await client.post(f"/api/v1/agents/{seeded_agent}/pause")
    assert res_bad_pause.status_code == 400
    assert "not running" in res_bad_pause.json()["detail"].lower()

    # 3. Resume agent (PAUSED -> RUNNING)
    res_resume = await client.post(f"/api/v1/agents/{seeded_agent}/resume")
    assert res_resume.status_code == 200
    assert res_resume.json()["status"] == "RUNNING"

    # 4. Stop agent (RUNNING -> COMPLETED)
    res_stop = await client.post(f"/api/v1/agents/{seeded_agent}/stop")
    assert res_stop.status_code == 200
    assert res_stop.json()["status"] == "COMPLETED"

    # Cannot start a completed agent
    res_bad_start = await client.post(f"/api/v1/agents/{seeded_agent}/start")
    assert res_bad_start.status_code == 400
    assert "cannot start a completed agent" in res_bad_start.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_agent(agents_test_env, seeded_agent):
    """DELETE /api/v1/agents/{id} deletes agent and cascades, but blocks deletion while RUNNING."""
    client: AsyncClient = agents_test_env["client"]
    session_factory = agents_test_env["session_factory"]

    # 1. Start agent -> attempt delete -> blocked 400
    await client.post(f"/api/v1/agents/{seeded_agent}/start")
    res_del_running = await client.delete(f"/api/v1/agents/{seeded_agent}")
    assert res_del_running.status_code == 400
    assert "cannot delete a running agent" in res_del_running.json()["detail"].lower()

    # 2. Stop agent -> attempt delete -> success 200
    await client.post(f"/api/v1/agents/{seeded_agent}/stop")
    res_del = await client.delete(f"/api/v1/agents/{seeded_agent}")
    assert res_del.status_code == 200
    assert res_del.json()["success"] is True

    # 3. Verify agent and cascaded AgentConfig are gone from DB
    async with session_factory() as db:
        agent_res = await db.execute(select(Agent).where(Agent.id == seeded_agent))
        assert agent_res.scalar_one_or_none() is None

        config_res = await db.execute(
            select(AgentConfig).where(AgentConfig.agent_id == seeded_agent)
        )
        assert config_res.scalar_one_or_none() is None

    # 4. Subsequent delete returns 404
    res_del_again = await client.delete(f"/api/v1/agents/{seeded_agent}")
    assert res_del_again.status_code == 404


@pytest.mark.asyncio
async def test_delete_agent_paused_success(agents_test_env):
    """DELETE /api/v1/agents/{id} succeeds when agent is in PAUSED state."""
    client: AsyncClient = agents_test_env["client"]

    # Create agent
    res = await client.post(
        "/api/v1/agents",
        json={
            "agent_name": "PausedDeleteAgent",
            "initial_capital": 100000.0,
            "mandate": {
                "strategy_style": "momentum",
                "objectives": ["Goal"],
                "preferred_indicators": ["EMA9"],
                "instrument": "RELIANCE",
                "timeframe": "15m",
                "risk_per_trade": 0.02,
                "max_position_exposure": 0.25,
                "max_daily_loss": 0.05,
            },
        },
    )
    agent_id = res.json()["agent_id"]

    # Start then pause agent
    await client.post(f"/api/v1/agents/{agent_id}/start")
    await client.post(f"/api/v1/agents/{agent_id}/pause")

    # Delete while paused succeeds
    del_res = await client.delete(f"/api/v1/agents/{agent_id}")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True


@pytest.mark.asyncio
async def test_cross_agent_isolation(agents_test_env):
    """Verifies that operations on one agent do not mutate or expose another agent."""
    client: AsyncClient = agents_test_env["client"]

    # Create Agent 1
    res1 = await client.post(
        "/api/v1/agents",
        json={
            "agent_name": "IsolatedAgentOne",
            "initial_capital": 100000.0,
            "mandate": {
                "strategy_style": "momentum",
                "objectives": ["Trend 1"],
                "preferred_indicators": ["EMA9"],
                "instrument": "RELIANCE",
                "timeframe": "15m",
                "risk_per_trade": 0.02,
                "max_position_exposure": 0.25,
                "max_daily_loss": 0.05,
            },
        },
    )
    agent1_id = res1.json()["agent_id"]

    # Create Agent 2
    res2 = await client.post(
        "/api/v1/agents",
        json={
            "agent_name": "IsolatedAgentTwo",
            "initial_capital": 150000.0,
            "mandate": {
                "strategy_style": "mean_reversion",
                "objectives": ["Mean 2"],
                "preferred_indicators": ["RSI14"],
                "instrument": "RELIANCE",
                "timeframe": "1h",
                "risk_per_trade": 0.01,
                "max_position_exposure": 0.15,
                "max_daily_loss": 0.03,
            },
        },
    )
    agent2_id = res2.json()["agent_id"]

    # Start Agent 1
    await client.post(f"/api/v1/agents/{agent1_id}/start")

    # Verify Agent 2 remains in READY state
    agent2_check = await client.get(f"/api/v1/agents/{agent2_id}")
    assert agent2_check.json()["status"] == "READY"
    assert agent2_check.json()["initial_capital"] == 150000.0
    assert agent2_check.json()["strategy_style"] == "mean_reversion"


@pytest.mark.asyncio
async def test_create_agent_simulation_conflict_already_associated(agents_test_env):
    """Attempting to associate a simulation that already has an agent returns 409 Conflict."""
    client: AsyncClient = agents_test_env["client"]
    session_factory = agents_test_env["session_factory"]

    # 1. Create a simulation already linked to an existing agent
    sim_id = "sim-conflict-409"
    async with session_factory() as db:
        inst = (
            await db.execute(
                select(models.Instrument).where(models.Instrument.symbol == "RELIANCE")
            )
        ).scalar_one()
        sim = SimulationRun(
            id=sim_id,
            agent_id="existing-agent-999",
            instrument_id=inst.id,
            timeframe="15m",
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
            initial_capital=100000.0,
            status=SimulationStatus.CREATED,
            is_baseline=False,
        )
        db.add(sim)
        await db.commit()

    # 2. Attempt to create new agent with this simulation_id -> 409
    payload = {
        "agent_name": "ConflictAgent",
        "initial_capital": 100000.0,
        "simulation_id": sim_id,
        "mandate": {
            "strategy_style": "momentum",
            "objectives": ["Goal"],
            "preferred_indicators": ["EMA9"],
            "instrument": "RELIANCE",
            "timeframe": "15m",
            "risk_per_trade": 0.02,
            "max_position_exposure": 0.25,
            "max_daily_loss": 0.05,
        },
    }
    res = await client.post("/api/v1/agents", json=payload)
    assert res.status_code == 409
    assert "already associated" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_agent_simulation_invalid_status_rejected(agents_test_env):
    """Attempting to associate a simulation in RUNNING or COMPLETED state returns 400 Bad Request."""
    client: AsyncClient = agents_test_env["client"]
    session_factory = agents_test_env["session_factory"]

    # 1. Create a completed simulation run
    sim_id = "sim-completed-status"
    async with session_factory() as db:
        inst = (
            await db.execute(
                select(models.Instrument).where(models.Instrument.symbol == "RELIANCE")
            )
        ).scalar_one()
        sim = SimulationRun(
            id=sim_id,
            agent_id=None,
            instrument_id=inst.id,
            timeframe="15m",
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
            initial_capital=100000.0,
            status=SimulationStatus.COMPLETED,
            is_baseline=False,
        )
        db.add(sim)
        await db.commit()

    # 2. Attempt to create agent linked to completed simulation -> 400
    payload = {
        "agent_name": "CompletedSimAgent",
        "initial_capital": 100000.0,
        "simulation_id": sim_id,
        "mandate": {
            "strategy_style": "momentum",
            "objectives": ["Goal"],
            "preferred_indicators": ["EMA9"],
            "instrument": "RELIANCE",
            "timeframe": "15m",
            "risk_per_trade": 0.02,
            "max_position_exposure": 0.25,
            "max_daily_loss": 0.05,
        },
    }
    res = await client.post("/api/v1/agents", json=payload)
    assert res.status_code == 400
    assert (
        "cannot associate agent with simulation in status 'completed'"
        in res.json()["detail"].lower()
    )


@pytest.mark.asyncio
async def test_update_agent_all_immutable_fields_rejected(agents_test_env, seeded_agent):
    """Attempting to mutate any immutable field via PATCH returns 422 Unprocessable Entity."""
    client: AsyncClient = agents_test_env["client"]

    immutable_attempts = [
        {"instrument": "TCS"},
        {"timeframe": "1h"},
        {"initial_capital": 500000.0},
        {"strategy_style": "scalping"},
        {"max_position_exposure": 0.50},
        {"max_daily_loss": 0.10},
        {"objectives": ["New objective"]},
        {"preferred_indicators": ["RSI14"]},
        {"simulation_id": "new-sim-id"},
        {"strategy_prompt": "Hacked prompt"},
    ]

    for forbidden_body in immutable_attempts:
        res = await client.patch(f"/api/v1/agents/{seeded_agent}", json=forbidden_body)
        assert res.status_code == 422, (
            f"Expected 422 for field {forbidden_body}, got {res.status_code}"
        )


@pytest.mark.asyncio
async def test_delete_agent_preserves_simulation_run_with_null_agent_id(agents_test_env):
    """Deleting an agent with a linked simulation sets simulation.agent_id to NULL without deleting the simulation."""
    client: AsyncClient = agents_test_env["client"]
    session_factory = agents_test_env["session_factory"]

    # 1. Create a simulation
    sim_id = "sim-retention-test"
    async with session_factory() as db:
        inst = (
            await db.execute(
                select(models.Instrument).where(models.Instrument.symbol == "RELIANCE")
            )
        ).scalar_one()
        sim = SimulationRun(
            id=sim_id,
            agent_id=None,
            instrument_id=inst.id,
            timeframe="15m",
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
            initial_capital=100000.0,
            status=SimulationStatus.CREATED,
            is_baseline=False,
        )
        db.add(sim)
        await db.commit()

    # 2. Create agent linked to this simulation
    create_res = await client.post(
        "/api/v1/agents",
        json={
            "agent_name": "RetentionAgent",
            "initial_capital": 100000.0,
            "simulation_id": sim_id,
            "mandate": {
                "strategy_style": "breakout",
                "objectives": ["Goal"],
                "preferred_indicators": ["EMA20"],
                "instrument": "RELIANCE",
                "timeframe": "15m",
                "risk_per_trade": 0.02,
                "max_position_exposure": 0.25,
                "max_daily_loss": 0.05,
            },
        },
    )
    assert create_res.status_code == 201
    agent_id = create_res.json()["agent_id"]

    # 3. Delete the agent
    del_res = await client.delete(f"/api/v1/agents/{agent_id}")
    assert del_res.status_code == 200

    # 4. Verify agent is deleted, but SimulationRun still exists with agent_id == None
    async with session_factory() as db:
        agent_check = await db.execute(select(Agent).where(Agent.id == agent_id))
        assert agent_check.scalar_one_or_none() is None

        sim_check = await db.execute(select(SimulationRun).where(SimulationRun.id == sim_id))
        sim_record = sim_check.scalar_one_or_none()
        assert sim_record is not None
        assert sim_record.agent_id is None
