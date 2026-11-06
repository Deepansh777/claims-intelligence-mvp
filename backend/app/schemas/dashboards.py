from pydantic import BaseModel, ConfigDict, Field

from app.llm.client import Effort
from app.llm.dashboard_schemas import MAX_TABS, DashboardOutline


class UserTab(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=500)


class OutlineRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    request: str = Field(min_length=1, max_length=2000)
    tabs: list[UserTab] = Field(default=[], max_length=MAX_TABS)
    effort: Effort = "medium"


class GenerateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    request: str = Field(min_length=1, max_length=2000)
    outline: DashboardOutline
    effort: Effort = "medium"
