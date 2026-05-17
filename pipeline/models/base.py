import os
import time

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

load_dotenv()

_engine = None
_SessionLocal = None

# 默认 DB URL 从环境变量读取，不再硬编码 sqlite
_DEFAULT_DB_URL = os.getenv("AIP_DB_URL", "postgresql://localhost/aip_db")


class Base(DeclarativeBase):
    pass


def _engine_kwargs(db_url: str) -> dict:
    if db_url.startswith(("postgresql://", "postgresql+")):
        return {"pool_pre_ping": True, "pool_recycle": 1800}
    return {}


def get_engine(db_url: str | None = None):
    global _engine
    if _engine is None:
        resolved_url = db_url or _DEFAULT_DB_URL
        _engine = create_engine(resolved_url, echo=False, **_engine_kwargs(resolved_url))
    return _engine


def get_session(db_url: str | None = None) -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(db_url))
    return _SessionLocal()


def commit_with_retry(
    session: Session,
    *,
    attempts: int = 3,
    sleep_seconds: float = 0.5,
) -> None:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            session.commit()
            return
        except (OperationalError, DisconnectionError) as exc:
            last_error = exc
            session.rollback()
            if attempt == attempts - 1:
                raise
            if sleep_seconds > 0:
                time.sleep(sleep_seconds * (2**attempt))
    if last_error is not None:
        raise last_error


def create_all(db_url: str | None = None):
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)
    try:
        from pipeline.db_migrate import run_migrations

        run_migrations(engine)
    except Exception:
        # Keep create_all usable in stripped-down test scenarios where migrations
        # may intentionally be unavailable or partially mocked.
        pass
