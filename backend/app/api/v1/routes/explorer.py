import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUser, get_current_user
from app.llm.schemas import QueryError, QueryResult
from app.schemas.explorer import QueryPage, QueryRequest
from app.services import explorer, sql_workspace

router = APIRouter(prefix="/explorer", dependencies=[Depends(get_current_user)])
User = Annotated[CurrentUser, Depends(get_current_user)]


def _error(status: int, detail: str, code: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail, "code": code})


def _not_found() -> JSONResponse:
    return _error(404, "Not found.", "not_found")


@router.get("/schemas")
async def list_schemas() -> list[dict]:
    return await explorer.schemas()


@router.get("/schemas/{schema}/tables")
async def list_tables(schema: str):
    try:
        return await explorer.tables(schema)
    except explorer.NotFound:
        return _not_found()


@router.get("/schemas/{schema}/tables/{table}/columns")
async def list_columns(schema: str, table: str):
    try:
        return await explorer.columns(schema, table)
    except explorer.NotFound:
        return _not_found()


@router.get("/schemas/{schema}/tables/{table}/preview", response_model=QueryResult)
async def preview(schema: str, table: str):
    try:
        return await explorer.preview(schema, table)
    except explorer.NotFound:
        return _not_found()
    except QueryError as e:
        return _error(502, str(e), "query_failed")


@router.post("/queries", response_model=QueryPage)
async def run_query(body: QueryRequest, user: User):
    try:
        q = await sql_workspace.run(user.id, body.id, body.sql)
    except QueryError as e:
        return _error(400, str(e), "invalid_sql")
    except sql_workspace.Duplicate:
        return _error(409, "A query with this id already exists.", "conflict")
    except sql_workspace.Busy:
        limit = sql_workspace.MAX_RUNNING_PER_USER
        return _error(429, f"You already have {limit} queries running.", "busy")
    return sql_workspace.page(body.id, q, 0)


@router.get("/queries/{query_id}", response_model=QueryPage)
async def query_page(query_id: uuid.UUID, user: User, page: Annotated[int, Query(ge=0)] = 0):
    q = sql_workspace.get(user.id, query_id)
    if q is None:
        return _error(404, "This result has expired. Run the query again.", "not_found")
    return sql_workspace.page(query_id, q, page)


@router.delete("/queries/{query_id}", status_code=204)
async def cancel_query(query_id: uuid.UUID, user: User):
    if not sql_workspace.cancel(user.id, query_id):
        return _not_found()
    return Response(status_code=204)
