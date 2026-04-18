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

## [2026-04-19] Task 1 — 引导式客户输入 UI

- CSS class 必须与模板实际使用的 class 名一致（ci-fields vs ci-field, ci-dot vs ci-progress-dot）
- 模板 JS 用 `style.display` 切换步骤可见性，不依赖 `.active` CSS class
- `create_project()` in input_layer.py 要求 ASIN 格式验证，新路由直接操作 Project 模型绕过
- 分步表单用 `data-step` 属性 + JS render() 函数实现，无需前端框架
- progress bar 用 width% 过渡 + 圆形数字 dot 指示器
- 13 新测试全通过，总计 264 passed（251 + 13）
- 5 个 test_brand_profile 失败是 pre-existing，与本次变更无关

## [Task 5] 三层标签体系
- assign_tags 集成到 slot_planner 时，必须在 expunge_all() 之后调用，否则 assign_tags 的 commit 会导致已 refresh 的 SlotPlan 对象 expired → DetachedInstanceError
- TagAssignment 的 tag_layer server_default='intent'，但显式传入 tag_layer 值时 server_default 不生效，无需 refresh 来获取
- UniqueConstraint 幂等处理：插入前 query 检查 existing，避免 IntegrityError
- _call_llm_for_scenes 独立为可 mock 的函数，测试通过 @patch 注入
