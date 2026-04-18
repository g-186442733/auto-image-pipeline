import json
import os
import re
from typing import List

from pipeline.models.qa_entry import QAEntry


def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` wrappers that Gemini sometimes adds."""
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*\n?(.*?)```\s*$", text, re.DOTALL)
    return m.group(1).strip() if m else text


_GEMINI_MODEL = "gemini-2.0-flash"

_QA_ANALYSIS_PROMPT = (
    "You are an Amazon Q&A analyst. Given the following customer questions and answers "
    "for ASIN {asin}, categorize them by topic. Return a JSON array where each element "
    "has: question (str), answer (str), frequency (int, estimated how often this type "
    "of question is asked), category (short topic label).\n\n"
    "Q&A pairs:\n{qa_text}\n\n"
    "Return ONLY valid JSON array, no markdown fences."
)


def _call_gemini(prompt: str) -> str:
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        return "[]"
    try:
        import google.generativeai as genai
    except ImportError:
        return "[]"
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(_GEMINI_MODEL)
    response = model.generate_content(prompt)
    return response.text


def analyze_qa(asin: str, qa_pairs: List[dict]) -> List[QAEntry]:
    if not qa_pairs:
        return []

    qa_text = "\n".join(
        f"Q: {q.get('question', '')}\nA: {q.get('answer', '')}" for q in qa_pairs
    )
    prompt = _QA_ANALYSIS_PROMPT.format(asin=asin, qa_text=qa_text)
    raw = _call_gemini(prompt)
    raw = _strip_markdown_fences(raw)

    try:
        entries = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(entries, list):
        return []

    result = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        result.append(
            QAEntry(
                asin=asin,
                question=e.get("question", ""),
                answer=e.get("answer", ""),
                frequency=e.get("frequency", 1),
                category=e.get("category", "general"),
            )
        )
    return result
