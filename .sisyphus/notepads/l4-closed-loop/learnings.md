# Learnings

## [2026-04-19] Session start

- Project: auto-image-pipeline (Python/Flask)
- venv: `source .venv/bin/activate`
- aip cmd: `PYTHONPATH=. python -m pipeline.__main__`
- Tests: `PYTHONPATH=. .venv/bin/pytest tests/ -q` (baseline: 211 passed)
- DB: SQLite, create_all(), no Alembic
- CSS: external style.css only, NO <style> inline
- Frontend: pure Jinja2 + vanilla JS, NO frameworks
- LLM: Gemini API (see brief_generator.py for pattern)
- All models in pipeline/models/, all layers in pipeline/layers/
- Web app: pipeline/web/app.py (Flask), templates in pipeline/web/templates/

## [2026-04-19] Task 0 — Schema 修复

- APlusContent.module_type CheckConstraint 用 `__table_args__` + `CheckConstraint("module_type IN (...)")`
- SQLite 对 CHECK 约束 INSERT/UPDATE 时强制执行，但仅对新表有效（ALTER TABLE 不支持 ADD CONSTRAINT）
- tag_assignments UniqueConstraint 用 `__table_args__` 中的 `UniqueConstraint(...)`
- tag_layer server_default='intent' 需要 `session.refresh(obj)` 后才可见
- 已有测试 test_aplus_content.py 用了旧枚举 STANDARD/PREMIUM，必须同步改为合法值（HERO/BENEFIT）
- ALTER TABLE 兼容语句放在 `__main__.py` 的 `_migrate_schema()`，用 try/except OperationalError 忽略 duplicate column
- 226 passed（基准 211 + 15 新测试）

## [2026-04-19] Task 3 — 品牌画像卡 UI

- 已有 `pipeline/models/brand.py` 使用 `brand_profiles` 表名，新模型需改用 `brand_profile_cards`
- `extend_existing=True` 防止多 test module import 时 MetaData 冲突
- `build_brand_profile()` 新建记录后需 `session.refresh(bp)` 再 `expunge`，否则 lazy-load 属性报 DetachedInstanceError
- 现有 SQLite DB 缺少 `customer_brief` 列，截图需用临时 DB（`create_all('sqlite:///tmp.db')`）
- 模板用 `dimensions` 列表（含 key/label/icon/value）统一渲染 10 卡片，避免硬编码
- 256 passed（基准 226 + 7 新测试 + 23 其他模块新增）
