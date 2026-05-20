from loguru import logger
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import get_settings
from app.models.domain import Document

settings = get_settings()
engine = create_engine(
    f"sqlite:///{settings.SQLITE_PATH}",
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


def check_sqlite() -> bool:
    try:
        with Session(engine) as session:
            session.exec(select(Document).limit(1))
    except SQLAlchemyError:
        logger.exception("Error checking SQLite")
        return False
    else:
        return True
