"""Helpers for migration-state inspection and native pipeline schema verification."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from sqlalchemy import create_engine, inspect, text

from database.models import (
    ComponentDefinition,
    ComponentProfile,
    ComponentVersion,
    ExecutionArtifact,
    PipelineBinding,
    PipelineDefinition,
    PipelineOutputAction,
    PipelineRun,
    PipelineStep,
    PipelineVersion,
    PlaygroundRun,
    StepRun,
)

BASELINE_ALEMBIC_REVISION = "dffd40c829a8"

_NATIVE_PIPELINE_TABLES = (
    ComponentDefinition.__table__,
    ComponentVersion.__table__,
    ComponentProfile.__table__,
    PipelineDefinition.__table__,
    PipelineVersion.__table__,
    PipelineStep.__table__,
    PipelineBinding.__table__,
    PipelineOutputAction.__table__,
    PipelineRun.__table__,
    StepRun.__table__,
    ExecutionArtifact.__table__,
    PlaygroundRun.__table__,
)


def native_pipeline_table_names() -> List[str]:
    return [table.name for table in _NATIVE_PIPELINE_TABLES]


def native_pipeline_tables() -> Iterable[Any]:
    return _NATIVE_PIPELINE_TABLES


def inspect_migration_state(database_url: str) -> Dict[str, Any]:
    engine = create_engine(database_url)
    try:
        table_names = set(inspect(engine).get_table_names())
        if not table_names:
            return {
                "status": "empty",
                "table_names": [],
                "current_revision": None,
                "should_stamp_baseline": False,
                "stamp_revision": None,
            }

        if "alembic_version" not in table_names:
            return {
                "status": "legacy_unversioned",
                "table_names": sorted(table_names),
                "current_revision": None,
                "should_stamp_baseline": True,
                "stamp_revision": BASELINE_ALEMBIC_REVISION,
            }

        with engine.connect() as connection:
            row = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
        current_revision = str(row[0]).strip() if row and row[0] else None
        if current_revision:
            return {
                "status": "versioned",
                "table_names": sorted(table_names),
                "current_revision": current_revision,
                "should_stamp_baseline": False,
                "stamp_revision": None,
            }

        return {
            "status": "legacy_unversioned",
            "table_names": sorted(table_names),
            "current_revision": None,
            "should_stamp_baseline": True,
            "stamp_revision": BASELINE_ALEMBIC_REVISION,
        }
    finally:
        engine.dispose()


def missing_native_pipeline_tables(database_url: str) -> List[str]:
    engine = create_engine(database_url)
    try:
        existing = set(inspect(engine).get_table_names())
        return [name for name in native_pipeline_table_names() if name not in existing]
    finally:
        engine.dispose()
