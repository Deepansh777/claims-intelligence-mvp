from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class CurrentUser:
    id: str
    is_admin: bool


def get_current_user() -> CurrentUser:
    return CurrentUser(id=settings.app_user_id, is_admin=settings.app_user_is_admin)
