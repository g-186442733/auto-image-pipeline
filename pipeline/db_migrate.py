from sqlalchemy import inspect, text

MIGRATIONS = [
    ("prompt_assets", "performance_score", "FLOAT DEFAULT NULL"),
    ("prompt_assets", "is_recommended", "BOOLEAN DEFAULT FALSE"),
    ("delivery_versions", "auto_delivered", "BOOLEAN DEFAULT FALSE"),
    ("delivery_versions", "client_signed_at", "TIMESTAMP DEFAULT NULL"),
    ("brand_profile_cards", "guidelines", "TEXT DEFAULT NULL"),
    ("competitor_listings", "price", "FLOAT DEFAULT NULL"),
    ("competitor_listings", "rating", "FLOAT DEFAULT NULL"),
    ("competitor_listings", "review_count", "INTEGER DEFAULT NULL"),
    ("competitor_listings", "main_image_url", "VARCHAR(512) DEFAULT NULL"),
    ("competitor_listings", "category_rank", "INTEGER DEFAULT NULL"),
    # Wave 2 Task 5: add tenant_id to 7 tables
    ("customer_briefs", "tenant_id", "INTEGER DEFAULT NULL"),
    ("decision_logs", "tenant_id", "INTEGER DEFAULT NULL"),
    ("feedback_actions", "tenant_id", "INTEGER DEFAULT NULL"),
    ("content_assets", "tenant_id", "INTEGER DEFAULT NULL"),
    ("hypotheses", "tenant_id", "INTEGER DEFAULT NULL"),
    ("pipeline_runs", "tenant_id", "INTEGER DEFAULT NULL"),
    ("trend_forecasts", "tenant_id", "INTEGER DEFAULT NULL"),
    # Task 8: 品牌三级拆分 — 新增 customer_profile_id 到 brand_profile_cards
    ("brand_profile_cards", "customer_profile_id", "INTEGER DEFAULT NULL"),
    # Wave 3: 产品详情 + 白底图/多角度图字段
    ("customer_briefs", "product_dimensions", "TEXT DEFAULT NULL"),
    ("customer_briefs", "product_weight", "TEXT DEFAULT NULL"),
    ("customer_briefs", "product_material", "TEXT DEFAULT NULL"),
    ("customer_briefs", "product_color", "TEXT DEFAULT NULL"),
    ("customer_briefs", "package_contents", "TEXT DEFAULT NULL"),
    ("customer_briefs", "product_certifications", "TEXT DEFAULT NULL"),
    ("customer_briefs", "listing_title", "TEXT DEFAULT NULL"),
    ("customer_briefs", "listing_keywords", "TEXT DEFAULT NULL"),
    ("customer_briefs", "listing_bullets", "TEXT DEFAULT NULL"),
    ("customer_briefs", "white_bg_image_path", "TEXT DEFAULT NULL"),
    ("customer_briefs", "multiangle_image_paths", "TEXT DEFAULT NULL"),
    # P1: projects 关联产品档案（一产品多次拍摄）
    ("projects", "product_profile_id", "INTEGER DEFAULT NULL"),
    # 飞轮写入字段（Phase 0）：A/B 结论、飞轮评分、上次更新时间
    ("brand_profile_cards", "ab_conclusions", "TEXT DEFAULT NULL"),
    ("brand_profile_cards", "flywheel_score", "FLOAT DEFAULT NULL"),
    ("brand_profile_cards", "last_flywheel_at", "TIMESTAMP DEFAULT NULL"),
    # Phase 3：prompt_assets 新增视觉标签（飞轮回写来源）
    ("prompt_assets", "visual_tags", "TEXT DEFAULT NULL"),
    ("prompt_assets", "user_edited", "BOOLEAN DEFAULT FALSE NOT NULL"),
    # 版本历史：三张 artifact 表关联 pipeline_run
    (
        "amazon_benchmarks",
        "pipeline_run_id",
        "INTEGER DEFAULT NULL REFERENCES pipeline_runs(id)",
    ),
    (
        "slot_plans",
        "pipeline_run_id",
        "INTEGER DEFAULT NULL REFERENCES pipeline_runs(id)",
    ),
    # Slot Planner v1.5：视觉策略字段 + 拍摄参数字段
    ("slot_plans", "visual_focus", "TEXT DEFAULT NULL"),
    ("slot_plans", "key_message", "TEXT DEFAULT NULL"),
    ("slot_plans", "competitor_contrast", "TEXT DEFAULT NULL"),
    ("slot_plans", "lighting_tag", "VARCHAR(50) DEFAULT NULL"),
    ("slot_plans", "angle_tag", "VARCHAR(30) DEFAULT NULL"),
    ("slot_plans", "dof_tag", "VARCHAR(30) DEFAULT NULL"),
    ("slot_plans", "background_tag", "VARCHAR(50) DEFAULT NULL"),
    ("slot_plans", "gen_params", "VARCHAR(200) DEFAULT NULL"),
    # Slot Planner v2: 标题、负向提示词、对比图结构
    ("slot_plans", "title", "VARCHAR(100) DEFAULT NULL"),
    ("slot_plans", "negative_prompt", "TEXT DEFAULT NULL"),
    ("slot_plans", "comparison_structure", "VARCHAR(200) DEFAULT NULL"),
    (
        "image_briefs",
        "pipeline_run_id",
        "INTEGER DEFAULT NULL REFERENCES pipeline_runs(id)",
    ),
    (
        "prompt_assets",
        "pipeline_run_id",
        "INTEGER DEFAULT NULL REFERENCES pipeline_runs(id)",
    ),
    # Per-slot 自定义提示词和参考图（规划确认阶段填写）
    ("slot_plans", "custom_prompt", "TEXT DEFAULT NULL"),
    ("slot_plans", "custom_image_paths", "TEXT DEFAULT NULL"),
    # A+ storyboard：每个模块关联推荐 slot 图
    ("aplus_contents", "slot_index", "INTEGER DEFAULT NULL"),
    # A/B 实测原始数据：保留 CTR/CVR 供 WebUI 回显
    ("prompt_assets", "ab_ctr", "FLOAT DEFAULT NULL"),
    ("prompt_assets", "ab_cvr", "FLOAT DEFAULT NULL"),
]

DROP_COLUMNS = [
    ("brand_profile_cards", "lora_type"),
    ("brand_profile_cards", "parent_category_lora_id"),
    ("tenants", "quota_loras"),
    # P3: brand_profile_cards.project_id 废弃，品牌层级通过 ProductProfile → Project 访问
    ("brand_profile_cards", "project_id"),
]

POSTGRES_CREATE_TABLES = [
    """CREATE TABLE IF NOT EXISTS pipeline_runs (
        id SERIAL PRIMARY KEY,
        project_id INTEGER NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        started_at TIMESTAMP DEFAULT NOW(),
        finished_at TIMESTAMP DEFAULT NULL,
        error_message TEXT,
        auto_triggered BOOLEAN DEFAULT FALSE,
        trigger_source VARCHAR(128)
    )""",
    """CREATE TABLE IF NOT EXISTS customer_profiles (
        id SERIAL PRIMARY KEY,
        tenant_id INTEGER NOT NULL,
        name VARCHAR(255) NOT NULL,
        industry VARCHAR(255),
        contact_email VARCHAR(255),
        notes TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS product_profiles (
        id SERIAL PRIMARY KEY,
        project_id INTEGER REFERENCES projects(id),
        brand_profile_id INTEGER REFERENCES brand_profile_cards(id),
        product_name VARCHAR(255),
        product_category VARCHAR(255),
        price_point VARCHAR(100),
        key_features TEXT,
        visual_notes TEXT,
        tenant_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS category_priors (
        id SERIAL PRIMARY KEY,
        category VARCHAR(255) NOT NULL UNIQUE,
        photo_style VARCHAR(100),
        model_type VARCHAR(100),
        scene_preference VARCHAR(100),
        composition_preference VARCHAR(100),
        material_texture VARCHAR(100),
        sample_count INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS drift_alerts (
        id SERIAL PRIMARY KEY,
        brand_profile_id INTEGER NOT NULL,
        field VARCHAR(100) NOT NULL,
        old_value TEXT,
        new_value TEXT,
        drift_score FLOAT,
        created_at TIMESTAMP DEFAULT NOW()
    )""",
]

SQLITE_CREATE_TABLES = [
    """CREATE TABLE IF NOT EXISTS pipeline_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        finished_at TIMESTAMP DEFAULT NULL,
        error_message TEXT,
        auto_triggered BOOLEAN DEFAULT FALSE,
        trigger_source VARCHAR(128)
    )""",
    """CREATE TABLE IF NOT EXISTS customer_profiles (
        id INTEGER PRIMARY KEY,
        tenant_id INTEGER NOT NULL,
        name VARCHAR(255) NOT NULL,
        industry VARCHAR(255),
        contact_email VARCHAR(255),
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS product_profiles (
        id INTEGER PRIMARY KEY,
        project_id INTEGER REFERENCES projects(id),
        brand_profile_id INTEGER REFERENCES brand_profile_cards(id),
        product_name VARCHAR(255),
        product_category VARCHAR(255),
        price_point VARCHAR(100),
        key_features TEXT,
        visual_notes TEXT,
        tenant_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS category_priors (
        id INTEGER PRIMARY KEY,
        category VARCHAR(255) NOT NULL UNIQUE,
        photo_style VARCHAR(100),
        model_type VARCHAR(100),
        scene_preference VARCHAR(100),
        composition_preference VARCHAR(100),
        material_texture VARCHAR(100),
        sample_count INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS drift_alerts (
        id INTEGER PRIMARY KEY,
        brand_profile_id INTEGER NOT NULL,
        field VARCHAR(100) NOT NULL,
        old_value TEXT,
        new_value TEXT,
        drift_score FLOAT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
]


def _get_columns(conn, table_name: str) -> set[str]:
    try:
        return {c["name"] for c in inspect(conn).get_columns(table_name)}
    except Exception:
        return set()


def _sync_postgres_sequences(conn) -> None:
    if conn.dialect.name != "postgresql":
        return

    inspector = inspect(conn)
    for table_name in inspector.get_table_names():
        if "id" not in _get_columns(conn, table_name):
            continue

        seq_name = conn.execute(
            text("SELECT pg_get_serial_sequence(:table_name, 'id')"),
            {"table_name": table_name},
        ).scalar()
        if not seq_name:
            continue

        conn.execute(
            text(
                f"SELECT setval('{seq_name}', COALESCE((SELECT MAX(id) FROM {table_name}), 0) + 1, false)"
            )
        )


def _create_missing_tables(conn) -> None:
    ddl_list = (
        SQLITE_CREATE_TABLES
        if conn.dialect.name == "sqlite"
        else POSTGRES_CREATE_TABLES
    )
    for ddl in ddl_list:
        conn.execute(text(ddl))


def run_migrations(engine):
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS brand_profiles"))

        # 创建新表
        _create_missing_tables(conn)

        # 添加新列
        for table_name, col_name, col_def in MIGRATIONS:
            existing_cols = _get_columns(conn, table_name)
            if not existing_cols:
                continue
            if col_name not in existing_cols:
                conn.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}")
                )

        # brand_profile_cards.project_id: 去掉 NOT NULL 和 UNIQUE 约束（列已删除时跳过）
        brand_cols = _get_columns(conn, "brand_profile_cards")
        if (
            conn.dialect.name == "postgresql"
            and brand_cols
            and "project_id" in brand_cols
        ):
            conn.execute(
                text(
                    "ALTER TABLE brand_profile_cards ALTER COLUMN project_id DROP NOT NULL"
                )
            )
            # 删除 unique 约束（名称由 PG 自动生成）
            conn.execute(
                text(
                    "ALTER TABLE brand_profile_cards DROP CONSTRAINT IF EXISTS brand_profile_cards_project_id_key"
                )
            )

        # product_profiles.project_id: 去掉 NOT NULL 和 UNIQUE 约束（迁移已有库）
        if conn.dialect.name == "postgresql" and _get_columns(conn, "product_profiles"):
            conn.execute(
                text(
                    "ALTER TABLE product_profiles ALTER COLUMN project_id DROP NOT NULL"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE product_profiles DROP CONSTRAINT IF EXISTS product_profiles_project_id_key"
                )
            )

        # 删除废弃列（LoRA 字段、P3 废弃字段）
        for table_name, col_name in DROP_COLUMNS:
            existing_cols = _get_columns(conn, table_name)
            if not existing_cols:
                continue
            if col_name in existing_cols:
                conn.execute(text(f"ALTER TABLE {table_name} DROP COLUMN {col_name}"))

        if conn.dialect.name == "postgresql" and _get_columns(
            conn, "brand_profile_cards"
        ):
            fk_exists = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.table_constraints "
                    "WHERE constraint_name='fk_brand_profile_cards_tenant_id' "
                    "AND table_name='brand_profile_cards'"
                )
            ).fetchone()
            if not fk_exists:
                conn.execute(
                    text(
                        "ALTER TABLE brand_profile_cards "
                        "ADD CONSTRAINT fk_brand_profile_cards_tenant_id "
                        "FOREIGN KEY (tenant_id) REFERENCES tenants(id)"
                    )
                )

        _sync_postgres_sequences(conn)

        # 版本历史：重建 amazon_benchmarks 唯一约束（旧约束不含 pipeline_run_id）
        if conn.dialect.name == "postgresql" and _get_columns(
            conn, "amazon_benchmarks"
        ):
            conn.execute(
                text(
                    "ALTER TABLE amazon_benchmarks "
                    "DROP CONSTRAINT IF EXISTS uq_benchmark_project_asin_image"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE amazon_benchmarks "
                    "DROP CONSTRAINT IF EXISTS uq_benchmark_project_asin_image_run"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE amazon_benchmarks "
                    "ADD CONSTRAINT uq_benchmark_project_asin_image_run "
                    "UNIQUE (project_id, competitor_asin, image_url, pipeline_run_id)"
                )
            )

        # 版本历史：清理 slot_plans 重复行（每三元组保留 id 最大那行）并加唯一约束
        if conn.dialect.name == "postgresql" and _get_columns(conn, "slot_plans"):
            conn.execute(
                text(
                    "DELETE FROM slot_plans WHERE id NOT IN ("
                    "SELECT MAX(id) FROM slot_plans "
                    "GROUP BY project_id, slot_index, pipeline_run_id)"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE slot_plans "
                    "DROP CONSTRAINT IF EXISTS uq_slot_plan_project_slot_run"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE slot_plans "
                    "ADD CONSTRAINT uq_slot_plan_project_slot_run "
                    "UNIQUE (project_id, slot_index, pipeline_run_id)"
                )
            )
            # 部分唯一索引：pipeline_run_id IS NULL 时防止重复行（UNIQUE 约束对 NULL 无效）
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_slot_plan_project_slot_null_run "
                    "ON slot_plans (project_id, slot_index) WHERE pipeline_run_id IS NULL"
                )
            )

        conn.commit()
