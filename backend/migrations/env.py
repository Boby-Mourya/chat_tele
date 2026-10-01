from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import inspect, pool, text
from sqlalchemy.ext.asyncio import async_engine_from_config

from northstar_api import (
    agent_purpose,  # noqa: F401
    course_knowledge_dispatch,  # noqa: F401
    course_knowledge_models,  # noqa: F401
    education,  # noqa: F401
    education_access_recovery,  # noqa: F401
    education_access_requests,  # noqa: F401
    education_batches,  # noqa: F401
    education_conversation_context,  # noqa: F401
    education_curricula,  # noqa: F401
    education_enrollment_events,  # noqa: F401
    education_enrollments,  # noqa: F401
    education_knowledge_lifecycle,  # noqa: F401
    education_knowledge_scope,  # noqa: F401
    education_papers,  # noqa: F401
    education_student_activity,  # noqa: F401
    education_student_identities,  # noqa: F401
    education_students,  # noqa: F401
    education_tutor,  # noqa: F401
    email_verification,  # noqa: F401
    help_models,  # noqa: F401
    mfa,  # noqa: F401
    models,  # noqa: F401
    telegram_provisioning,  # noqa: F401
    notifications,  # noqa: F401
    onboarding_models,  # noqa: F401
    password_reset,  # noqa: F401
    subscriptions,  # noqa: F401
    workspace_api_keys,  # noqa: F401
    workspace_invitations,  # noqa: F401
)
from northstar_api.config import get_settings
from northstar_api.database import Base
from northstar_api.lead_crm import audit_models, channel_models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        if connection.dialect.name == "postgresql":
            inspector = inspect(connection)
            if not inspector.has_table("alembic_version"):
                connection.execute(
                    text("CREATE TABLE alembic_version (version_num VARCHAR(128) NOT NULL PRIMARY KEY)")
                )
            elif (
                next(
                    column
                    for column in inspector.get_columns("alembic_version")
                    if column["name"] == "version_num"
                )["type"].length
                < 128
            ):
                connection.execute(
                    text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")
                )
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
