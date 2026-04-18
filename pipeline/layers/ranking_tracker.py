from datetime import datetime, timedelta

from pipeline.models.asin_ranking import ASINRanking


def record_ranking(session, project_id, asin, keyword, position, category=""):
    ranking = ASINRanking(
        project_id=project_id,
        asin=asin,
        keyword=keyword,
        rank_position=position,
        category_name=category,
    )
    session.add(ranking)
    session.commit()
    return ranking


def get_ranking_history(session, project_id, asin, keyword, days=30):
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = (
        session.query(ASINRanking)
        .filter(
            ASINRanking.project_id == project_id,
            ASINRanking.asin == asin,
            ASINRanking.keyword == keyword,
            ASINRanking.tracked_at >= cutoff,
        )
        .order_by(ASINRanking.tracked_at.asc())
        .all()
    )
    return [
        {
            "rank_position": r.rank_position,
            "tracked_at": r.tracked_at,
            "category_name": r.category_name,
        }
        for r in rows
    ]


def get_ranking_summary(session, project_id):
    from sqlalchemy import func as sa_func

    subq = (
        session.query(
            ASINRanking.asin,
            sa_func.max(ASINRanking.id).label("max_id"),
        )
        .filter(ASINRanking.project_id == project_id)
        .group_by(ASINRanking.asin)
        .subquery()
    )
    rows = session.query(ASINRanking).join(subq, ASINRanking.id == subq.c.max_id).all()
    return [
        {
            "asin": r.asin,
            "keyword": r.keyword,
            "rank_position": r.rank_position,
            "category_name": r.category_name,
            "tracked_at": r.tracked_at,
        }
        for r in rows
    ]
