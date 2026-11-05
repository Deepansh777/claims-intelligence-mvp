from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import get_current_user
from app.llm.schemas import QueryError, QueryResult
from app.services import explorer

router = APIRouter(prefix="/explorer", dependencies=[Depends(get_current_user)])


def _not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Not found.", "code": "not_found"})


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
        return JSONResponse(status_code=502, content={"detail": str(e), "code": "query_failed"})
