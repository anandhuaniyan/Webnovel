from __future__ import annotations

import os
from logging.config import fileConfig
from urllib.parse import urlparse

from sqlalchemy import engine_from_config, pool

from alembic import context
from app import models  # noqa: F401
from app.core.database import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get("WEBNOVEL_DATABASE_URL", "")
if not database_url:
    raise RuntimeError("WEBNOVEL_DATABASE_URL is required; migration aborted")

parsed = urlparse(database_url.replace("postgresql+psycopg", "postgresql", 1))
database_name = parsed.path.lstrip("/").split("?", 1)[0]
database_port = parsed.port or 5432
print("Webnovel migration target:")
print(f"  host: {parsed.hostname}")
print(f"  port: {database_port}")
print(f"  name: {database_name}")
if database_name != "webnovel":
    raise RuntimeError(f"migration target must be database 'webnovel', got '{database_name}'")

config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
