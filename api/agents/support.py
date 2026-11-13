import os

from openai import AsyncOpenAI, omit
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai_compatible import OpenAICompatibleProvider
from pydantic_ai_harness import SummarizingCompaction

from config import Settings

INSTRUCTIONS = """Ты помощник БАРС Груп. Отвечай кратко и на языке пользователя.
Помогай с общими вопросами и учитывай контекст диалога. Если для ответа
нужны внутренние сведения БАРС, скажи, что у тебя пока нет доступа к ним.
Не выдумывай внутренние правила, контакты и ссылки."""


def build_model_client(settings: Settings) -> AsyncOpenAI:
    # The SDK also imports ambient OpenAI headers. Use only this provider's credentials.
    headers = {
        line.partition(":")[0].strip(): omit
        for line in os.environ.get("OPENAI_CUSTOM_HEADERS", "").splitlines()
        if ":" in line
    }
    api_key = (
        settings.chat_api_key.get_secret_value() if settings.chat_api_key else None
    )
    headers.update(
        {
            "Authorization": f"Bearer {api_key}" if api_key else omit,
            "OpenAI-Organization": omit,
            "OpenAI-Project": omit,
        }
    )
    return AsyncOpenAI(
        base_url=str(settings.chat_base_url),
        api_key=api_key or "local-provider",
        default_headers=headers,
        max_retries=0,
        timeout=20,
    )


def build_agent(settings: Settings, client: AsyncOpenAI) -> Agent[None, str]:
    model = OpenAIChatModel(
        settings.chat_model,
        provider=OpenAICompatibleProvider("bars-chat", openai_client=client),
    )
    window = settings.chat_context_window
    model_settings = OpenAIChatModelSettings(max_tokens=min(window // 8, 1600))
    if settings.chat_api_key is None:
        model_settings["extra_headers"] = {"Authorization": omit}

    return Agent(
        model,
        output_type=str,
        instructions=INSTRUCTIONS,
        model_settings=model_settings,
        capabilities=[
            SummarizingCompaction(
                model=model,
                model_settings=model_settings,
                max_fraction=0.8,
                context_window=window,
                keep_tokens=min(window // 4, 8000),
                preserve_first_user_message=False,
                incremental=True,
            )
        ],
    )
