"""The only place chat models are built."""

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.core.config import settings

Effort = Literal["low", "medium", "high"]


class StructuredOutputError(Exception):
    pass


def get_chat_model(effort: Effort) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        use_responses_api=True,
        reasoning={"effort": effort},
        timeout=settings.openai_timeout_seconds,
        max_retries=2,
        stream_usage=True,
    )


async def call_structured[T: BaseModel](
    schema: type[T], system: str, prompt: str, effort: Effort, config: RunnableConfig
) -> T:
    structured = get_chat_model(effort).with_structured_output(schema, include_raw=True)
    result = await structured.ainvoke([SystemMessage(system), HumanMessage(prompt)], config=config)
    if result["parsed"] is None:
        raise StructuredOutputError(f"unusable {schema.__name__}: {result['parsing_error']}")
    return result["parsed"]
