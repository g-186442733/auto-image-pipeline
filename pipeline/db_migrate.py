from sqlalchemy import inspect, text

MIGRATIONS = [
    ("prompt_assets", "performance_score", "FLOAT DEFAULT NULL"),
    ("prompt_assets", "is_recommended", "BOOLEAN DEFAULT 0"),
    ("delivery_versions", "auto_delivered", "BOOLEAN DEFAULT 0"),
    ("delivery_versions", "client_signed_at", "DATETIME DEFAULT NULL"),
    ("brand_profile_cards", "guidelines", "TEXT DEFAULT NULL"),
]


def run_migrations(engine):
    inspector = inspect(engine)
    with engine.connect() as conn:
        for table_name, col_name, col_def in MIGRATIONS:
            try:
                existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
            except Exception:
                continue
            if col_name not in existing_cols:
                conn.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}")
                )
        conn.commit()
