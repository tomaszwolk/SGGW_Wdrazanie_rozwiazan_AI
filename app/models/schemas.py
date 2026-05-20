# TODO
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    sqlite_connection: str
    qdrant_connection: str
