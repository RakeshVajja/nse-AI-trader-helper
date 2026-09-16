"""SQLAlchemy Model Registry.

Imports all models so Base.metadata is fully populated for Alembic migrations.
"""

from app.database.models.agent import (
    Agent,
    AgentAction,
    AgentConfig,
    AgentDecision,
    AgentStatus,
    AgentToolCall,
    AgentUsage,
)
from app.database.models.market import (
    Candle,
    Instrument,
    InstrumentType,
    MarketDataRange,
)
from app.database.models.trading import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    PortfolioSnapshot,
    Position,
    SimulationRun,
    SimulationStatus,
    Trade,
)

__all__ = [
    "Agent",
    "AgentAction",
    "AgentConfig",
    "AgentDecision",
    "AgentStatus",
    "AgentToolCall",
    "AgentUsage",
    "Candle",
    "Instrument",
    "InstrumentType",
    "MarketDataRange",
    "Order",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PortfolioSnapshot",
    "Position",
    "SimulationRun",
    "SimulationStatus",
    "Trade",
]
