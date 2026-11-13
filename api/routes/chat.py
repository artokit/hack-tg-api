import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from openai import OpenAIError
from pydantic_ai.exceptions import AgentRunError
from sqlalchemy.exc import SQLAlchemyError

from routes.dependencies import get_chat_service, get_live_turns, require_bot
from schemas.chat import ChatRequest, ChatResponse, ResetRequest, TurnMessage
from services.chat import ChatService, ConversationBusy
from services.live_turns import LiveTurns, TurnClosed

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["agent"], dependencies=[Depends(require_bot)])
ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]
LiveTurnsDep = Annotated[LiveTurns, Depends(get_live_turns)]


@router.post("/chat/stream", response_class=EventSourceResponse)
async def stream_chat(
    data: TurnMessage, turns: LiveTurnsDep
) -> AsyncIterator[ServerSentEvent]:
    try:
        async with aclosing(
            turns.stream(data.telegram_user_id, data.turn_id, data.text)
        ) as events:
            async for event in events:
                yield ServerSentEvent(event=event.kind, data=event.text)
    except ConversationBusy:
        yield ServerSentEvent(event="error", data="busy")
    except TimeoutError:
        yield ServerSentEvent(event="error", data="timeout")
    except (AgentRunError, OpenAIError, SQLAlchemyError) as exc:
        logger.warning("Agent stream failed (%s)", type(exc).__name__)
        yield ServerSentEvent(event="error", data="unavailable")


@router.post("/chat/steer", status_code=202)
async def steer(data: TurnMessage, turns: LiveTurnsDep) -> Response:
    try:
        turns.steer(data.telegram_user_id, data.turn_id, data.text)
    except TurnClosed:
        raise HTTPException(409, "No matching active turn") from None
    return Response(status_code=202)


@router.post("/chat")
async def chat(data: ChatRequest, service: ChatServiceDep) -> ChatResponse:
    try:
        answer = await service.reply(data.telegram_user_id, data.text)
    except ConversationBusy:
        raise HTTPException(409, "Conversation is busy") from None
    except TimeoutError:
        raise HTTPException(504, "Agent response timed out") from None
    except (AgentRunError, OpenAIError, SQLAlchemyError) as exc:
        logger.warning("Agent request failed (%s)", type(exc).__name__)
        raise HTTPException(503, "Agent is temporarily unavailable") from None
    return ChatResponse(answer=answer)


@router.post("/reset", status_code=204)
async def reset(data: ResetRequest, service: ChatServiceDep) -> Response:
    try:
        await service.reset(data.telegram_user_id)
    except ConversationBusy:
        raise HTTPException(409, "Conversation is busy") from None
    except TimeoutError:
        raise HTTPException(504, "Conversation reset timed out") from None
    except SQLAlchemyError as exc:
        logger.warning("Conversation reset failed (%s)", type(exc).__name__)
        raise HTTPException(503, "Agent is temporarily unavailable") from None
    return Response(status_code=204)
