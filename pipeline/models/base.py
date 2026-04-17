from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

_engine = None
_SessionLocal = None


class Base(DeclarativeBase):
    pass


def get_engine(db_url: str = "sqlite:///data/pipeline.db"):
    global _engine
    if _engine is None:
        _engine = create_engine(db_url, echo=False)
    return _engine


def get_session(db_url: str = "sqlite:///data/pipeline.db") -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(db_url))
    return _SessionLocal()


def create_all(db_url: str = "sqlite:///data/pipeline.db"):
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)
