"""
services/study_tutor.py
-----------------------
Student mode AI tutor for document-grounded Q&A.
"""

import logging
from dataclasses import dataclass

from openai import OpenAI

from app.config import settings
from app.services.rag_service import search_similar_chunks

logger = logging.getLogger(__name__)

TUTOR_MODEL = "gpt-5.4-mini"

_openai_client = OpenAI(api_key=settings.openai_api_key)


@dataclass
class StudyTutorResponse:
    answer: str
    sources: list[dict]


TUTOR_SYSTEM_PROMPT = """\
당신은 업로드된 학습 자료를 기반으로 답변하는 AI 튜터입니다.

규칙:
- 반드시 제공된 학습 자료 발췌 안의 정보만 근거로 답변하세요.
- 자료에 없는 내용은 추측하지 말고, 업로드한 자료만으로는 확인하기 어렵다고 말하세요.
- 한국어로 친절하고 명확하게 설명하세요.
- 답변은 학습자가 바로 이해할 수 있도록 2~5문장 정도로 작성하세요.
- 필요한 경우 짧은 예시를 들 수 있지만, 예시도 자료 내용에서 벗어나지 않아야 합니다.
"""


def _format_sources(chunks: list[dict]) -> str:
    if not chunks:
        return "(관련 자료를 찾지 못했습니다.)"

    lines = []
    for i, chunk in enumerate(chunks, start=1):
        page = chunk.get("page_number")
        chunk_index = chunk.get("chunk_index")
        label = f"자료 {i}"
        if page is not None:
            label += f" / {page}페이지"
        if chunk_index is not None:
            label += f" / 청크 {chunk_index}"
        lines.append(f"[{label}]\n{chunk.get('content', '')}")
    return "\n\n".join(lines)


def _format_history(history: list[dict], last_n: int = 6) -> str:
    recent = history[-last_n:] if len(history) > last_n else history
    if not recent:
        return "(이전 대화 없음)"

    lines = []
    for msg in recent:
        role = "사용자" if msg.get("role") == "user" else "AI 튜터"
        lines.append(f"{role}: {msg.get('content', '')}")
    return "\n".join(lines)


def _build_user_prompt(
    topic: str,
    question: str,
    conversation_history: list[dict],
    rag_chunks: list[dict],
) -> str:
    return f"""\
=== 학습 주제 ===
{topic}

=== 이전 대화 ===
{_format_history(conversation_history)}

=== 학습 자료 발췌 ===
{_format_sources(rag_chunks)}

=== 사용자 질문 ===
{question}
"""


def answer_study_question(
    db,
    document_id: int,
    topic: str,
    question: str,
    conversation_history: list[dict],
    model: str = TUTOR_MODEL,
) -> StudyTutorResponse:
    """
    Answer a learner's question using only RAG chunks from the uploaded document.
    """
    rag_chunks = search_similar_chunks(
        db=db,
        document_id=document_id,
        query=question,
        top_k=5,
    )

    user_prompt = _build_user_prompt(
        topic=topic,
        question=question,
        conversation_history=conversation_history,
        rag_chunks=rag_chunks,
    )

    logger.info(
        "Study tutor call — document_id=%d | chunks=%d",
        document_id,
        len(rag_chunks),
    )

    response = _openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": TUTOR_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
    )

    answer = response.choices[0].message.content.strip()
    sources = [
        {
            "chunk_index": chunk.get("chunk_index"),
            "page_number": chunk.get("page_number"),
        }
        for chunk in rag_chunks
    ]

    return StudyTutorResponse(answer=answer, sources=sources)
