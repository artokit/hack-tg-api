import asyncio

from pydantic_ai import Agent, ConversationTypeAdapter
from pydantic_ai.messages import CompactionPart, ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai_harness import SummarizingCompaction


def test_compacted_snapshot_resumes_and_updates_summary() -> None:
    summaries: list[str] = []

    def summarize(messages: list[ModelMessage], _info) -> ModelResponse:
        summaries.append(repr(messages))
        return ModelResponse(
            parts=[TextPart(f"Факт: проект Маяк. Резюме {len(summaries)}.")]
        )

    def answer(messages: list[ModelMessage], info) -> ModelResponse:
        assert not info.function_tools
        has_summary = any(
            isinstance(part, CompactionPart)
            for message in messages
            for part in message.parts
        )
        return ModelResponse(parts=[TextPart("Маяк" if has_summary else "Принято")])

    async def scenario() -> None:
        agent = Agent(
            FunctionModel(answer),
            capabilities=[
                SummarizingCompaction(
                    model=FunctionModel(summarize),
                    max_tokens=450,
                    keep_tokens=100,
                    preserve_first_user_message=False,
                    incremental=True,
                )
            ],
        )
        conversation = None
        marker = "OLD_VERBATIM_TEXT"
        for prompt in (
            marker,
            "word " * 240,
            "next",
            "more " * 280,
            "last",
            "more " * 350,
            "end",
        ):
            result = await agent.run(prompt, conversation=conversation)
            snapshot = ConversationTypeAdapter.dump_python(
                result.conversation, mode="json"
            )
            conversation = ConversationTypeAdapter.validate_python(snapshot)

        assert len(summaries) >= 2
        assert marker in summaries[0]
        assert "Резюме 1." in summaries[1]
        assert marker not in repr(snapshot)
        assert "end" in repr(snapshot)
        assert result.output == "Маяк"
        assert any(
            isinstance(part, CompactionPart)
            and part.content is not None
            and f"Резюме {len(summaries)}." in part.content
            for message in conversation.messages
            for part in message.parts
        )

    asyncio.run(scenario())
