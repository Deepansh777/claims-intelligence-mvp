import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.llm.client import Effort


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=2000)
    network: Literal["NEXUS", "PCN", "BOTH"] = "NEXUS"
    effort: Effort = "medium"
    client_request_id: uuid.UUID | None = None


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime


class ConversationSummary(ConversationOut):
    preview: str | None
    network: str | None
    last_activity: datetime
    expires_at: datetime
    stale: bool
