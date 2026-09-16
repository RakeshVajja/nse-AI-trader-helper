"""Service layer coordinating agent failure handling, simulation control, and DB persistence.

Provides:
- High-level AgentSafetyService wrapper around AgentFailureHandler
- Authoritative SimulationService auto-pause callback integration
- Transactionally safe persistence of AgentStatus.PAUSED
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models
from app.database.models.agent import AgentStatus
from app.trading.agent.safety.handler import AgentFailureHandler
from app.trading.agent.safety.schemas import AgentFailureState, FailurePolicyConfig
from app.trading.simulation.service import SimulationService

logger = logging.getLogger(__name__)


class AgentSafetyService:
    """Service managing failure handling, auto-pause coordination, and persistence."""

    def __init__(
        self,
        config: Optional[FailurePolicyConfig] = None,
        simulation_service: Optional[SimulationService] = None,
        handler: Optional[AgentFailureHandler] = None,
    ) -> None:
        self.config = config or FailurePolicyConfig()
        self.simulation_service = simulation_service
        self.handler = handler or AgentFailureHandler(config=self.config)

        if self.simulation_service is not None:
            self._configure_simulation_service_pause()

    def attach_simulation_service(self, simulation_service: SimulationService) -> None:
        """Attach authoritative simulation service and wire auto-pause callback."""
        self.simulation_service = simulation_service
        self._configure_simulation_service_pause()

    def _configure_simulation_service_pause(self) -> None:
        """Attach authoritative simulation service pause callback to handler."""

        async def _pause_sim(sim_id: Optional[str], agent_id: str, reason: str) -> None:
            if not sim_id or self.simulation_service is None:
                return
            try:
                sim_service = self.simulation_service
                if hasattr(sim_service, "session_factory") and callable(
                    getattr(sim_service, "session_factory", None)
                ):
                    async with sim_service.session_factory() as db:
                        await sim_service.pause_simulation(simulation_id=sim_id, db=db)
                else:
                    await sim_service.pause_simulation(simulation_id=sim_id, db=None)
                logger.info(
                    "Simulation '%s' (agent '%s') auto-paused via SimulationService: %s",
                    sim_id,
                    agent_id,
                    reason,
                )
            except Exception:
                logger.exception("Failed to auto-pause simulation '%s'", sim_id)

        self.handler.pause_callback = _pause_sim

    def create_pause_callback(self, agent_id: str, db: Optional[AsyncSession] = None):
        """Create a callable callback invoking simulation pause."""

        def _cb(sim_id: Optional[str], aid: str, reason: str) -> None:
            if self.handler.pause_callback:
                import asyncio
                import inspect

                if inspect.iscoroutinefunction(self.handler.pause_callback):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self.handler.pause_callback(sim_id, aid, reason))
                    except RuntimeError:
                        asyncio.run(self.handler.pause_callback(sim_id, aid, reason))
                else:
                    self.handler.pause_callback(sim_id, aid, reason)

        return _cb

    async def persist_agent_pause_state(
        self,
        db: AsyncSession,
        agent_id: str,
        state_or_reason: Optional[Any] = None,
        reason: Optional[str] = None,
    ) -> bool:
        """Persist PAUSED status to PostgreSQL agent entity transactionally."""
        try:
            stmt = select(models.Agent).where(models.Agent.id == agent_id)
            res = await db.execute(stmt)
            agent = res.scalar_one_or_none()
            if agent is not None:
                if isinstance(state_or_reason, AgentFailureState):
                    agent.status = (
                        AgentStatus.PAUSED if state_or_reason.is_paused else AgentStatus.RUNNING
                    )
                else:
                    agent.status = AgentStatus.PAUSED
                await db.commit()
                logger.info(
                    "Agent '%s' status updated to %s in database",
                    agent_id,
                    agent.status.value,
                )
                return True
            return False
        except Exception:
            await db.rollback()
            logger.exception("Failed to persist pause state for agent '%s'", agent_id)
            raise
