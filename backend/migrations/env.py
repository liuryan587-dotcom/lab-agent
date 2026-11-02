from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.database import Base

# Import every model so SQLAlchemy registers all tables before autogenerate.
import app.models.agent_trace  # noqa: F401
import app.models.chat_message  # noqa: F401
import app.models.equipment  # noqa: F401
import app.models.lab  # noqa: F401
import app.models.pending_action  # noqa: F401
import app.models.reservation  # noqa: F401
import app.models.user  # noqa: F401

target_metadata = Base.metadata
database_url = settings.DATABASE_URL
if context.config.config_file_name:
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)


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
    connectable = create_engine(database_url, poolclass=NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
