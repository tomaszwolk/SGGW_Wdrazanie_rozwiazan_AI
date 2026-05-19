# TODO
from sqlmodel import Session, SQLModel, create_engine

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
