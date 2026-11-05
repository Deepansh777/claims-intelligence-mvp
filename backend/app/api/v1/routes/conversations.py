import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import CurrentUser, get_current_user
from app.schemas.ask import AskRequest, ConversationOut
from app.services import ask_service

router = APIRouter(prefix="/conversations")
User = Annotated[CurrentUser, Depends(get_current_user)]


def _error(status: int, detail: str, code: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail, "code": code})


@router.post("", status_code=201)
async def create_conversation(user: User) -> ConversationOut:
    return ConversationOut(**await ask_service.create_conversation(user))


@router.post("/{conversation_id}/messages/stream")
async def stream_message(conversation_id: uuid.UUID, body: AskRequest, user: User):
    try:
        prep = await ask_service.prepare(user, conversation_id, body)
    except ask_service.NotFound:
        return _error(404, "Conversation not found.", "not_found")
    except ask_service.Conflict as e:
        return _error(409, str(e), "conflict")
    except ask_service.RateLimited:
        return _error(429, "Too many questions in the last hour. Try again later.", "rate_limited")
    return StreamingResponse(
        ask_service.stream(prep),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
