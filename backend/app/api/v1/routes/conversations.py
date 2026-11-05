import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import CurrentUser, get_current_user
from app.schemas.ask import AskRequest, ConversationOut, ConversationSummary
from app.services import ask_service, conversation_service

router = APIRouter(prefix="/conversations")
runs_router = APIRouter(prefix="/runs")
meta_router = APIRouter()
User = Annotated[CurrentUser, Depends(get_current_user)]


def _error(status: int, detail: str, code: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail, "code": code})


def _not_found(what: str) -> JSONResponse:
    return _error(404, f"{what} not found.", "not_found")


@router.get("")
async def list_conversations(user: User) -> list[ConversationSummary]:
    return await conversation_service.list_conversations(user)


@router.post("", status_code=201)
async def create_conversation(user: User) -> ConversationOut:
    return ConversationOut(**await conversation_service.create_conversation(user))


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: uuid.UUID, user: User):
    found = await conversation_service.get_conversation(user, conversation_id)
    return found if found is not None else _not_found("Conversation")


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: uuid.UUID, user: User):
    if not await conversation_service.delete_conversation(user, conversation_id):
        return _not_found("Conversation")
    return Response(status_code=204)


@router.post("/{conversation_id}/messages/stream")
async def stream_message(conversation_id: uuid.UUID, body: AskRequest, user: User):
    try:
        prep = await ask_service.prepare(user, conversation_id, body)
    except ask_service.NotFound:
        return _not_found("Conversation")
    except ask_service.Conflict as e:
        return _error(409, str(e), "conflict")
    except ask_service.RateLimited:
        return _error(429, "Too many questions in the last hour. Try again later.", "rate_limited")
    return StreamingResponse(
        ask_service.stream(prep),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@runs_router.post("/{run_id}/rerun")
async def rerun(run_id: uuid.UUID, user: User):
    try:
        return await ask_service.rerun(user, run_id)
    except ask_service.NotFound:
        return _not_found("Answer")
    except ask_service.Conflict as e:
        return _error(409, str(e), "conflict")
    except ask_service.RateLimited:
        return _error(429, "Too many questions in the last hour. Try again later.", "rate_limited")


@runs_router.get("/{run_id}/export.csv")
async def export_csv(run_id: uuid.UUID, user: User, query: Literal["q1", "q2", "q3"] = "q1"):
    body = await conversation_service.export_csv(user, run_id, query)
    if body is None:
        return _not_found("Result")
    return Response(
        body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="result-{run_id}-{query}.csv"'},
    )


@meta_router.get("/meta")
async def meta(user: User) -> dict:
    return await conversation_service.meta(user)
