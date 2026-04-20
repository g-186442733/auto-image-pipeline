## [2026-04-20] Session Init

### 项目关键事实

- Python 3.14 venv at `.venv/`
- Flask app: `pipeline/web/app.py` (1112 行), port 9010, 4 blueprints
- DB: SQLite `data/pipeline.db`, env var `AIP_DB_URL`
- 34 张 ORM 表, Base at `pipeline/models/base.py`
- `db_migrate.py` 用手工 ALTER TABLE，无 Alembic
- tests/ 目录已存在，有大量 test\_\*.py

### DB 现状

- 26 张表已有 nullable tenant_id
- 7 张表缺 tenant_id: customer_briefs, decision_logs, feedback_actions, content_assets, hypotheses, pipeline_runs, trend_forecasts
- Tenant 模型存在但从未在路由层使用
- 6 个模型未在 **init**.py 导出: DecisionLog, FeedbackAction, ContentAsset, Hypothesis, PipelineRun, TrendForecast

### PostgreSQL 现状

- PostgreSQL 未安装 (psycopg2 未装, pg_isready 不存在)
- 需要: brew install postgresql + brew services start + createdb + pip install psycopg2-binary
- .env 当前: AIP_DB_URL=sqlite:///data/pipeline.db

### 不可修改项

- /input/new 和 /input/<id>/edit 的任何逻辑
- customer_input.html
- 路由结构 (app.py 路由不重构)

### 约束

- 服务重启: launchctl kickstart -k gui/$(id -u)/com.axureboutique.{service}
- 当前服务: nohup 临时拉起, PID 3976, 端口 9010 (无 plist, 无法 launchctl)
- 无 Alembic, 继续用 db_migrate.py

### .env 文件路径

`/Users/axureboutique/Projects/auto-image-pipeline/.env`

### venv 激活

`source /Users/axureboutique/Projects/auto-image-pipeline/.venv/bin/activate`

## [2026-04-20] Task 2: Model Exports

- 6 个缺失模型文件均已存在于 pipeline/models/：decision_log.py, feedback_action.py, content_asset.py, hypothesis.py, pipeline_run.py, trend_forecast.py
- 类名与文件名一一对应（snake_case → PascalCase）
- 在 **init**.py 末尾追加 6 个 import + **all** 条目即可
- 验证命令：AIP_DB_URL=sqlite:///test.db .venv/bin/python -c "from pipeline.models import DecisionLog, ...; print('OK')" → 输出 OK

## [2026-04-20] Task 3: pytest Infrastructure

### 完成内容

- 更新 `tests/conftest.py`：添加 PG 测试基础设施（`AIP_DB_URL`、`pg_engine`、`db_session` fixtures）
- 保留 `sqlite_session` fixture 向后兼容
- 添加 `_pg_available()` + `_ensure_test_db()` 优雅处理 PG 不可用情况（skip 而非 error）
- 在 `pyproject.toml` 添加 `pythonpath = ["."]`，无需手动设 PYTHONPATH

### 测试结果

- `pytest --collect-only`：930 tests collected，无报错
- `pytest -x -q`：242 passed，1 failed（已有业务逻辑测试 `/project/new` 期望 302 返回 200，与 conftest 无关）

### 关键决策

- `db_session` fixture 依赖 `pg_engine`，PG 不可用时整个 session skip（不 error）
- transaction rollback 模式保证每个测试数据隔离
- `AIP_TEST_DB_URL` 环境变量默认 `postgresql://localhost/aip_test_db`

## [2026-04-20] Task 1: PostgreSQL Migration

### 完成内容

- PostgreSQL 16 via `brew install postgresql@16`, 服务已启动
- 数据库 `aip_db` 已创建，无密码本地认证 (trust)
- `.env` 更新: `AIP_DB_URL=postgresql://localhost/aip_db`
- `pipeline/models/base.py`: 移除 SQLite 硬编码默认值，改用 `os.getenv("AIP_DB_URL")` + `load_dotenv()`
- `pipeline/config.py`: fallback default 改为 PG URL
- `pipeline/db_migrate.py`: `BOOLEAN DEFAULT 0` → `BOOLEAN DEFAULT FALSE`, `DATETIME` → `TIMESTAMP`
- 32 张 ORM 表在 PG 中创建成功
- SQLite 数据迁移: 1044 行中 ~1041 行成功（3 行孤立 FK 数据跳过）

### 关键发现

- `base.py` 中 `get_engine()`、`get_session()`、`create_all()` 三处都硬编码了 SQLite URL 作为默认参数
- PG 严格类型: BOOLEAN 列不接受整数 0/1，需 Python 层 `bool()` 转换
- PG 严格 FK: 孤立引用数据（如 `reference_packs.project_id=88888`）被拒绝，可接受
- `brand_profiles` 表被 `db_migrate.py` 的 `DROP TABLE IF EXISTS` 删除，导致 32 而非 34 张表
- 测试文件中 `sqlite:///:memory:` 是测试专用，无需修改

## [2026-04-20] Task 4: User Model + Session Auth

### 完成内容

- `pipeline/models/user.py`: User 模型 (id, email, password_hash, tenant_id FK, created_at, is_active)
- `pipeline/models/__init__.py`: 导出 User
- `pipeline/web/app.py`: 添加 `/login` (GET+POST), `/logout` 路由, `login_required` decorator
- `pipeline/web/templates/login.html`: 最小登录表单
- `tests/test_auth.py`: 6 个测试全部通过

### 关键发现

- app.py 已有 `secret_key` 设置 (line 120, 使用 `FLASK_SECRET_KEY` env var 或 `secrets.token_hex`)，无需额外设置 `SECRET_KEY`
- `create_all()` 在 `create_app()` 中调用，User model 通过 `__init__.py` import chain 注册到 Base.metadata
- auth 测试不能用 conftest 的 `db_session` fixture（它用独立 PG 连接+rollback），需直接用 `model_get_session()` 并手动清理
- `login_required` decorator 定义在 `create_app()` 内部闭包中，当前未应用到任何路由（等后续任务逐步保护路由）
- 测试总数从 930 增长到 936（+6 auth tests）
- `datetime.utcnow()` 有 deprecation warning，后续应改用 `datetime.now(datetime.UTC)`

## [2026-04-20] Task 8: Brand 三级拆分完成

### 完成内容

- 新建 CustomerProfile 模型 (`pipeline/models/customer_profile.py`)
- 新建 ProductProfile 模型 (`pipeline/models/product_profile.py`)
- BrandProfile 删除 `lora_type` / `parent_category_lora_id`，新增 `customer_profile_id` FK
- db_migrate.py 追加 CREATE TABLE + ALTER TABLE + DROP COLUMN 迁移
- brand_profiler.py 新增 `get_brand_hierarchy()` 三级链路查找
- prompt_engine.py 改用三级查找，注入 customer.industry + product 信息
- input_layer.py 扩展 optional_fields（messaging_pillars, customer_profile_id）
- app.py 新增 3 组 API 路由：/api/customers, /api/customers/<id>/brands, /api/projects/<id>/product-profile
- 新建 tests/test_brand_hierarchy.py（5 tests, all passed）

### 关键发现

- `get_brand_hierarchy()` 使用优雅降级：product→brand→customer 任一环节缺失都不报错，返回 None
- PG 的 DROP COLUMN 需要 inspector 检查列是否存在再决定是否执行
- 测试 fixture 用 module scope + session_transaction 注入 auth，与 test_tenant_isolation.py 模式一致

## F-DA-07 价格带定位分析 (Task 13) — 2026-04-20

- AmazonBenchmark 没有 price 字段，只有 score (Float)。用 score 作为数值代理进行百分位计算。
- AmazonBenchmark 也没有 product_category，需要 join ProductProfile 来匹配同类目竞品。
- ProductProfile.price_point 是 String 类型（如 "$29.99"），需要正则解析为 float。
- 路由模式：lazy import in route handler, 400/404/200 三档响应，与 brand_auto_update 一致。
- 测试用 8 个竞品覆盖完整百分位分布，确保 price_band 逻辑可测。

## F-GEN-06 Tri-engine Fan-out (Task 14) — 2026-04-20

- `ThreadPoolExecutor` + dict comprehension 的 futures 顺序不确定，测试不能假设 score 与 engine 的对应关系
- 解法：测试验证 best_engine 与 max score 一致即可，不硬编码具体引擎
- stub 模式：random.seed 保证确定性测试，mock side_effect 在多线程场景下不可靠
- 路由插入位置：price-band-analysis 之后、upload 之前
