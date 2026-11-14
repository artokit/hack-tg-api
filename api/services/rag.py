import asyncio
import logging
import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from agents.rag import Luna, QueryPart
from models.rag import RagUnavailable
from repositories.rag_extract import identifiers
from repositories.rag_index import RagIndex
from repositories.rag_jobs import RagJobs
from schemas.rag import RagAnswerRead, RagPartRead, RagSourceRead


log = logging.getLogger(__name__)
PART_TIMEOUT_SECONDS = 36
REGISTRY = re.compile(
    r"\bреестр(?:а|е|у|ом|ы|ов)?\s+[«\"]?(мебели|техники)\b", re.IGNORECASE
)
INLINE_EVIDENCE_ID = re.compile(r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}:\d+\b", re.I)


@dataclass
class AnswerPart:
    part: RagPartRead
    sources: list[RagSourceRead]


class RagService:
    def __init__(self, jobs: RagJobs, index: RagIndex, luna: Luna):
        self.jobs = jobs
        self.index = index
        self.luna = luna

    async def submit(
        self, source_id: str, title: str, source_url: str | None, format: str, data: bytes
    ) -> UUID:
        return await self.jobs.enqueue(self.index.key, source_id, title, source_url, format, data)

    async def read_job(self, job_id: UUID):
        return await self.jobs.read(job_id, self.index.key)

    async def answer(self, question: str, standalone: str | None) -> RagAnswerRead:
        try:
            async with asyncio.timeout(49):
                return await self.find_answer(question, standalone)
        except TimeoutError as error:
            raise RagUnavailable("answer_timeout") from error
        except SQLAlchemyError as error:
            raise RagUnavailable("index_unavailable") from error

    async def find_answer(self, question: str, standalone: str | None) -> RagAnswerRead:
        explicit = identifiers(question)
        contextual = identifiers(standalone or "")
        if len(explicit) > 6:
            return RagAnswerRead(status="clarify", parts=[RagPartRead(
                question=question, status="ambiguous",
                clarification="Укажи до шести пунктов за один вопрос.",
            )], sources=[])
        versions = await self.jobs.active_versions(self.index.key)
        if not versions:
            return RagAnswerRead(status="not_found", parts=[], sources=[])
        planned = await self.luna.plan_query(question, standalone, explicit)
        allowed_semantic_ids = set(contextual) - set(explicit)
        valid_plan = (
            {part.exact_id for part in planned.parts if part.exact_id} == set(explicit)
            and all(
                set(identifiers(part.question)) <= (
                    {part.exact_id} if part.exact_id else allowed_semantic_ids
                )
                for part in planned.parts
            )
        )
        if len(explicit) == 1 and len(planned.parts) == 1:
            parts = [QueryPart(question=question[:1200], exact_id=explicit[0])]
        elif valid_plan:
            parts = [
                QueryPart(question=part.question, exact_id=part_ids[0])
                if not part.exact_id and len(part_ids := identifiers(part.question)) == 1
                and part_ids[0] in allowed_semantic_ids
                else part
                for part in planned.parts
            ]
        elif explicit:
            parts = [QueryPart(question=question[:1200], exact_id=identifier) for identifier in explicit]
        elif standalone and len(contextual) == 1:
            parts = [QueryPart(question=standalone[:1200], exact_id=contextual[0])]
        else:
            parts = [QueryPart(question=question[:1200])]
        outcomes = await asyncio.gather(
            *(self.resolve_with_deadline(part, versions, question) for part in parts),
            return_exceptions=True,
        )
        results: list[AnswerPart] = []
        for part, outcome in zip(parts, outcomes, strict=True):
            if isinstance(outcome, RagUnavailable):
                results.append(AnswerPart(RagPartRead(
                    question=part.question, status="unsupported",
                    clarification="Поиск по этой части вопроса временно недоступен.",
                ), []))
            elif isinstance(outcome, BaseException):
                raise outcome
            else:
                results.append(outcome)
        if any(isinstance(outcome, RagUnavailable) for outcome in outcomes) and not any(
            result.part.status == "supported" for result in results
        ):
            raise RagUnavailable("answer_unavailable")
        response_parts = [result.part for result in results]
        sources = {source.id: source for result in results for source in result.sources}
        if all(part.status == "supported" for part in response_parts):
            status = "answered"
        elif any(part.status == "supported" for part in response_parts):
            status = "partial"
        elif any(part.status == "ambiguous" for part in response_parts):
            status = "clarify"
        else:
            status = "not_found"
        return RagAnswerRead(status=status, parts=response_parts, sources=list(sources.values()))

    async def resolve_with_deadline(
        self, part: QueryPart, versions: list[str], original: str
    ) -> AnswerPart:
        try:
            async with asyncio.timeout(PART_TIMEOUT_SECONDS):
                return await self.resolve(part, versions, original)
        except TimeoutError as error:
            raise RagUnavailable("answer_timeout") from error

    async def resolve(self, part: QueryPart, versions: list[str], original: str) -> AnswerPart:
        default = AnswerPart(RagPartRead(question=part.question, status="unsupported"), [])
        if part.exact_id:
            chunks = await self.index.exact(part.exact_id, versions)
            log.info("RAG retrieval (exact, %d candidates)", len(chunks))
            if not chunks:
                default.part.clarification = f"Пункт {part.exact_id} не найден в базе."
                return default
        else:
            chunks = await self.index.semantic(part.question, versions)
            log.info("RAG retrieval (semantic, %d candidates)", len(chunks))
            related = list(dict.fromkeys(ref for chunk in chunks[:3] for ref in chunk["related"]))[:6]
            chunks.extend(await self.index.related(related, versions))
        evidence = self.evidence(chunks, part.exact_id)
        named_registries = {match.casefold() for match in REGISTRY.findall(original)}
        registries = named_registries if len(named_registries) == 1 else {
            match.casefold() for match in REGISTRY.findall(part.question)
        }
        if len(registries) == 1:
            evidence = {
                key: block for key, block in evidence.items()
                if registries & {
                    match.casefold() for match in REGISTRY.findall(
                        " ".join([block["title"], block["text"], *block["section"]])
                    )
                }
            }
        if not evidence:
            return default
        proposal = await self.luna.propose(part.question, list(evidence.values()))
        statement = INLINE_EVIDENCE_ID.sub("", proposal.statement)
        statement = re.sub(r"\[[,\s]*\]", "", statement).strip()
        if proposal.status == "ambiguous" and proposal.clarification.strip():
            return AnswerPart(RagPartRead(
                question=part.question, status="ambiguous", clarification=proposal.clarification.strip()
            ), [])
        selected = list(dict.fromkeys(proposal.evidence_ids))
        if (
            proposal.status != "supported" or not statement or not selected
            or any(key not in evidence for key in selected)
        ):
            return default
        verification = [evidence[key] for key in selected]
        if any(block["kind"] in ("visual", "scan") for block in verification):
            verification.extend([
                block for key, block in evidence.items()
                if key not in selected and block["kind"] not in ("visual", "scan")
                and any(evidence[ref]["title"] == block["title"] for ref in selected)
            ][:4])
        checked = await self.luna.verify(
            part.question, statement, verification, original,
        )
        if not checked.supported or not checked.citations:
            return default
        sources = []
        seen = set()
        verified_ids = {block["id"] for block in verification}
        for citation in checked.citations:
            if citation.id not in verified_ids:
                return default
            block = evidence[citation.id]
            source = self.source(block, citation.quote)
            if source is None:
                return default
            if source.id not in seen:
                seen.add(source.id)
                sources.append(source)
        return AnswerPart(RagPartRead(
            question=part.question, status="supported", statement=statement,
            source_ids=[source.id for source in sources],
        ), sources)

    @staticmethod
    def evidence(chunks: list[dict], identifier: str | None) -> dict[str, dict]:
        found: dict[str, dict] = {}
        size = 0
        for chunk in chunks:
            for block in chunk["evidence"]:
                if block["id"] in found or identifier and identifier not in block["identifiers"]:
                    continue
                size += len(block["text"])
                if size > 23500:
                    return found
                found[block["id"]] = {
                    **block, "title": chunk["title"], "source_url": chunk["source_url"],
                    "format": chunk["format"],
                }
        return found

    @staticmethod
    def source(block: dict, proposed_quote: str | None) -> RagSourceRead | None:
        visual = block["kind"] in ("visual", "scan")
        quote = None
        if not visual:
            quote = proposed_quote.strip() if proposed_quote else ""
            if not quote or quote not in block["text"]:
                return None
        url = block["source_url"]
        if url and block["format"] == "pdf" and block["page"] and "#" not in url:
            url += f"#page={block['page']}"
        return RagSourceRead(
            id=block["id"] + (f":{block['text'].index(quote)}:{len(quote)}" if quote else ""),
            title=block["title"], url=url, page=block["page"],
            section=block["section"], identifiers=block["identifiers"],
            quote=quote, visual=visual,
        )
