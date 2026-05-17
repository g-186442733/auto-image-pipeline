from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from pipeline.models.knowledge_entry import KnowledgeEntry, VALID_CATEGORIES
from pipeline.models.prompt_asset import PromptAsset


def add_entry(
    session: Session,
    source_project_id: int | None,
    category: str,
    title: str,
    content: str,
    tags: str = "",
    tenant_id: int = 1,
) -> KnowledgeEntry:
    if category not in VALID_CATEGORIES:
        raise ValueError(
            f"Invalid category '{category}'. Must be one of {VALID_CATEGORIES}"
        )
    entry = KnowledgeEntry(
        source_project_id=source_project_id,
        category=category,
        title=title,
        content=content,
        tags=tags,
        tenant_id=tenant_id,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def search_entries(
    session: Session,
    query: str,
    category: str | None = None,
    limit: int = 10,
) -> list[KnowledgeEntry]:
    q = session.query(KnowledgeEntry)
    if category:
        q = q.filter(KnowledgeEntry.category == category)
    if query:
        q = q.filter(
            or_(
                KnowledgeEntry.title.like(f"%{query}%"),
                KnowledgeEntry.content.like(f"%{query}%"),
            )
        )
    return q.order_by(KnowledgeEntry.created_at.desc()).limit(limit).all()


def get_popular_entries(
    session: Session,
    category: str | None = None,
    limit: int = 10,
) -> list[KnowledgeEntry]:
    q = session.query(KnowledgeEntry)
    if category:
        q = q.filter(KnowledgeEntry.category == category)
    return q.order_by(KnowledgeEntry.usage_count.desc()).limit(limit).all()


def increment_usage(session: Session, entry_id: int) -> KnowledgeEntry | None:
    entry = session.get(KnowledgeEntry, entry_id)
    if entry is None:
        return None
    entry.usage_count = (entry.usage_count or 0) + 1
    session.commit()
    session.refresh(entry)
    return entry


def promote_to_knowledge(prompt_asset: PromptAsset, session: Session) -> KnowledgeEntry:
    title = f"prompt_asset#{prompt_asset.id}"
    existing = (
        session.query(KnowledgeEntry).filter(KnowledgeEntry.title == title).first()
    )
    if existing is not None:
        return existing

    tags = prompt_asset.model_name or ""
    return add_entry(
        session,
        source_project_id=prompt_asset.project_id,
        category="prompt_pattern",
        title=title,
        content=prompt_asset.prompt_text,
        tags=tags,
    )


def delete_entry(session: Session, entry_id: int, tenant_id: int) -> bool:
    entry = (
        session.query(KnowledgeEntry)
        .filter(
            KnowledgeEntry.id == entry_id,
            KnowledgeEntry.tenant_id == tenant_id,
        )
        .first()
    )
    if entry is None:
        return False
    session.delete(entry)
    session.commit()
    return True
