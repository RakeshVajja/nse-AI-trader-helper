"""Unit tests for Alembic database migrations upgrade and downgrade lifecycles."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import alembic.command
import alembic.config
import pytest
from sqlalchemy import create_engine, inspect


@pytest.fixture
def temp_migration_db():
    """Create a temporary SQLite database file and provide an Alembic config targeting it."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_migration.db")
    db_url = f"sqlite:///{db_path}"

    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    alembic_cfg = alembic.config.Config(str(ini_path))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    yield {"url": db_url, "config": alembic_cfg, "db_path": db_path}

    if os.path.exists(db_path):
        os.remove(db_path)
    if os.path.exists(temp_dir):
        os.rmdir(temp_dir)


def test_alembic_upgrade_and_downgrade_lifecycle(temp_migration_db):
    """Verify that migrations upgrade to head and downgrade to base cleanly."""
    cfg = temp_migration_db["config"]
    db_url = temp_migration_db["url"]

    # 1. Upgrade to head
    alembic.command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    expected_tables = {
        "alembic_version",
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
    assert expected_tables.issubset(table_names)
    engine.dispose()

    # 2. Downgrade to base
    alembic.command.downgrade(cfg, "base")

    engine = create_engine(db_url)
    inspector = inspect(engine)
    downgraded_tables = set(inspector.get_table_names())
    # All entity tables must be dropped, only alembic_version (or nothing) remains
    assert "instruments" not in downgraded_tables
    assert "candles" not in downgraded_tables
    assert "simulation_runs" not in downgraded_tables
    assert "agents" not in downgraded_tables
    engine.dispose()

    # 3. Upgrade to head again
    alembic.command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    inspector = inspect(engine)
    reupgraded_tables = set(inspector.get_table_names())
    assert expected_tables.issubset(reupgraded_tables)
    engine.dispose()
