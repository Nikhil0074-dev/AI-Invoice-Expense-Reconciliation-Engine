from alembic import context

from app import models  # noqa: F401  (register tables)
from app.core.config import get_settings
from app.db.base import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = get_settings().database_url
    if url.startswith("sqlite:///") and ":memory:" not in url:  # fresh checkout: ./data does not exist yet
        import os
        os.makedirs(os.path.dirname(os.path.abspath(url.replace("sqlite:///", "", 1))), exist_ok=True)
    return url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import create_engine
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                          render_as_batch=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
