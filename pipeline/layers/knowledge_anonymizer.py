import re

from pipeline.models.knowledge_entry import KnowledgeEntry

_ORDER_RE = re.compile(r"#?ORD-\d+")
_PATH_RE = re.compile(r"/[\w/]+\.\w+")


def _scrub(text: str, brand_list: list[str]) -> str:
    for brand in brand_list:
        text = re.sub(re.escape(brand), "[BRAND]", text, flags=re.IGNORECASE)
    text = _ORDER_RE.sub("[ORDER_ID]", text)
    text = _PATH_RE.sub("[PATH]", text)
    return text


def anonymize_knowledge(entry: KnowledgeEntry, brand_list: list[str]) -> KnowledgeEntry:
    d = entry.__dict__.copy()
    d["title"] = _scrub(d.get("title", ""), brand_list)
    d["content"] = _scrub(d.get("content", ""), brand_list)
    copy = KnowledgeEntry.__new__(KnowledgeEntry)
    copy.__dict__.update(d)
    return copy
