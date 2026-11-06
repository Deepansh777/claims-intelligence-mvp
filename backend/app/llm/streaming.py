"""The gate between a LangGraph run and the client (methodology-docs/llm-best-practices.md §4).

Only explicit public status messages pass. Graph state is handed to the caller for
persistence and must never be forwarded as-is; tokens are not streamed because answers
must be validated before the user sees any figure.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

MAX_STATUS_LEN = 200


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def run_gated(graph, inputs: dict, config: dict) -> AsyncIterator[tuple[str, Any]]:
    """Yields ("status", {"message": str, "step": str | None}) and ("state", latest graph state)."""
    async for mode, data in graph.astream(inputs, config=config, stream_mode=["custom", "values"]):
        if mode == "custom" and isinstance(data, dict) and data.get("public"):
            message = str(data["message"])[:MAX_STATUS_LEN]
            yield "status", {"message": message, "step": data.get("step")}
        elif mode == "values":
            yield "state", data
