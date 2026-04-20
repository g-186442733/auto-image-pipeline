# Learnings

## 2026-04-19 Session Start
- `create_all()` 不会给已有表加列——db_migrate.py 必须在所有任务之前完成
- QARecord.score 是 Float，可直接用作置信度数据源
- orchestrator step_qa() 已有 retry: _QA_MAX_RETRIES=2, _QA_PASS_THRESHOLD=70
- Config 模式: dataclass + os.getenv() + field(default_factory=lambda:...)
- 测试 fixture 3种: (A) engine+session, (B) autouse _db, (C) reset_db
- 测试命令: PYTHONPATH=. .venv/bin/pytest tests/ -q
- 基线: 456 passed, 不可退化
- 项目路径: /Users/axureboutique/Projects/auto-image-pipeline
## 2026年 4月19日 星期日 22时56分25秒 CST Task-1
- db_migrate.py: run_migrations(engine) 用 inspect().get_columns() 检查列是否存在再 ALTER TABLE
- delivery_version.py 已有 auto_delivered/client_signed_at，无需加列
- prompt_asset.py 新增 performance_score(Float) / is_recommended(Boolean)
- 3 tests: fresh/idempotent/missing-table — all PASS
- 基线从 409 passed → 451 passed（+42），8 failures 均为 test_e2e_tws/test_e2e_pipeline 的跨测试隔离问题，单独运行均 PASS

## [2026-04-19] Task-6 飞轮
- flywheel.py: run_flywheel 接受 qa_score 参数以支持测试 mock
- config.py: 3 个新 flag 字段用 field(default_factory=lambda:...) 模式
- orchestrator.py: step_deliver 末尾添加 flywheel 触发入口（纯 import guard）
- delivery_version.py: 添加 auto_delivered Column（ORM 层，配合 db_migrate ALTER TABLE）
