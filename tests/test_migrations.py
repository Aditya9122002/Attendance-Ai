from pathlib import Path

from alembic import command
from alembic.config import Config

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def test_migrations_apply_and_match_models(tmp_path):
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{tmp_path.as_posix()}/m.db")
    command.upgrade(config, "head")
    command.check(config)  # fails if the models differ from what the migrations build
