import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from openai import OpenAIError
from pydantic_ai.exceptions import AgentRunError
from sqlalchemy.exc import SQLAlchemyError

from routes.dependencies import get_chat_service, require_bot
from schemas.chat import ChatRequest, ChatResponse, ResetRequest
from services.chat import ChatService, ConversationBusy

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["agent"], dependencies=[Depends(require_bot)])
ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


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
