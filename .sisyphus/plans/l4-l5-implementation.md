# L4 补完 + L5 建设实现计划

## TL;DR

> **Quick Summary**: 为 auto-image-pipeline 实现 L4 层两项补完（置信度评分路由、品类知识匿名化）和 L5 层三项新功能（A/B 归因引擎、趋势预测引擎、全自动飞轮），采用 TDD 模式，Wave 0 先建 DB 迁移工具解决 `create_all()` 不加列的核心风险。
>
> **Deliverables**:
>
> - DB 迁移工具 `pipeline/db_migrate.py`（幂等 ALTER TABLE）
> - 置信度评分路由（orchestrator `step_qa()` 三段路由）
> - 知识匿名化（KnowledgeEntry regex-based 脱敏）
> - A/B 归因引擎（CSV/JSON 导入 + performance_score 计算）
> - 趋势预测引擎（Keepa 数据驱动 TrendForecast 模型）
> - 全自动飞轮（Config flag 控制 L1→L4 自动触发）
>
> **Estimated Effort**: Large
> **Parallel Execution**: YES - 4 waves (Wave 0 → Wave 1 parallel → Wave 2 parallel → Wave 3)
> **Critical Path**: Wave 0 (db_migrate) → Wave 2 (A/B + Trend need new columns) → Wave 3 (flywheel needs all)

---

## Context

### Original Request

老板要求实现 L4 补完和 L5 建设，共 5 个功能模块。远期目标是基于完整系统撰写订单 SOP 操作手册。

### Interview Summary

**Key Discussions**:

- 5 做 4 不做：做置信度路由、知识匿名化、A/B 归因、趋势预测、全自动飞轮；不做品牌 LoRA、SaaS 多租户、品类 LoRA、内容获客闭环
- DB 迁移不用 Alembic，用 `create_all()` + 手写 `ALTER TABLE`
- 测试策略 TDD，基线 456 passed
- A/B 归因公式：`performance_score = 0.6×CTR + 0.4×CVR`，阈值 ≥0.75 标记 `is_recommended`
- 趋势引擎用 `amazon_data.py` 已有 Keepa 数据，不新建 `keepa_analyzer.py`
- 飞轮默认关闭，总开关 + 逐步开关，Config dataclass + env var 模式

**Research Findings**:

- `create_all()` 不会给已有表加列——必须先建 `db_migrate.py`
- QARecord.score 是 Float，可直接作置信度输入
- orchestrator `step_qa()` 内已有 retry 逻辑（`_QA_MAX_RETRIES=2`, `_QA_PASS_THRESHOLD=70`）
- Config 模式：dataclass + `os.getenv()` + `field(default_factory=lambda:...)`
- 测试 fixture 3 种模式：(A) engine+session, (B) autouse `_db`, (C) reset_db

### Metis Review

**Identified Gaps** (addressed):

- `create_all()` 不加列风险 → Wave 0 建 db_migrate.py
- PromptAsset/DeliveryVersion 是已有表需 ALTER TABLE → db_migrate 幂等处理
- 匿名化应为单向不可逆 → guardrail 写入计划
- 每个 commit 独立通过全部测试 → TDD 强制

---

## Work Objectives

### Core Objective

为 auto-image-pipeline 补全 L4 层缺失功能并建设 L5 层，使系统从"人工主导"进化到"可配置自动化"。

### Concrete Deliverables

- `pipeline/db_migrate.py` — 幂等迁移工具
- `pipeline/orchestrator.py` 修改 — 置信度路由逻辑
- `pipeline/layers/knowledge_anonymizer.py` — 匿名化模块
- `pipeline/layers/ab_attribution.py` — A/B 归因引擎
- `pipeline/models/prompt_asset.py` 修改 — 新增 2 字段
- `pipeline/layers/trend_engine.py` — 趋势预测引擎
- `pipeline/models/trend_forecast.py` — TrendForecast 模型
- `pipeline/config.py` 修改 — 飞轮 feature flags
- `pipeline/models/delivery_version.py` 修改 — 新增 2 字段
- `pipeline/layers/flywheel.py` — 飞轮编排器
- 对应全部测试文件

### Definition of Done

- [ ] `PYTHONPATH=. .venv/bin/pytest tests/ -q` → 全部 PASS（≥456 + 新测试）
- [ ] 每个 feature 可独立开关
- [ ] 无破坏性变更（已有 456 测试不变）

### Must Have

- 幂等 DB 迁移（重复运行不报错）
- 置信度三段路由（高≥80/中≥50/低<50）
- 匿名化 regex 覆盖品牌名、订单号、路径
- `performance_score = 0.6×CTR + 0.4×CVR`，≥0.75 标 `is_recommended`
- TrendForecast 模型含品类热度分数 + 趋势标记
- 飞轮总开关 + 逐步开关，默认关闭

### Must NOT Have (Guardrails)

- 不加新 API 端点、不改 UI、不加调度器
- 不修改 `amazon_data.py`——趋势引擎只读取
- 不建反查表（匿名化单向不可逆）
- 置信度路由最多 3 种策略（不做更复杂的）
- 不做品牌/品类 LoRA、SaaS 多租户、内容获客闭环
- 不引入新的第三方依赖（除非绝对必要并说明理由）

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed. No exceptions.

### Test Decision

- **Infrastructure exists**: YES
- **Automated tests**: TDD (RED→GREEN→REFACTOR)
- **Framework**: pytest（项目已有）
- **Baseline**: 456 passed（不可退化）

### QA Policy

Every task MUST include agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **DB/Model**: Use Bash (pytest) — 运行迁移、验证 schema、CRUD 测试
- **Business Logic**: Use Bash (pytest) — 单元测试 + 集成测试
- **Config**: Use Bash (pytest + env var) — 验证 flag 开关行为

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 0 (Foundation — must complete first):
└── Task 1: DB Migration Utility [quick]

Wave 1 (After Wave 0 — parallel, no new columns needed):
├── Task 2: 置信度评分路由 [deep]
└── Task 3: 品类知识匿名化 [deep]

Wave 2 (After Wave 0 — parallel, need ALTER TABLE):
├── Task 4: A/B 归因引擎 [deep]
└── Task 5: 趋势预测引擎 [deep]

Wave 3 (After Wave 0+1+2 — depends on all):
└── Task 6: 全自动飞轮 [deep]

Wave FINAL (After ALL tasks — 4 parallel reviews):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA (unspecified-high)
└── Task F4: Scope fidelity check (deep)
-> Present results -> Get explicit user okay
```

### Dependency Matrix

| Task           | Depends On | Blocks    |
| -------------- | ---------- | --------- |
| 1 (db_migrate) | —          | 2,3,4,5,6 |
| 2 (置信度路由) | 1          | 6         |
| 3 (知识匿名化) | 1          | 6         |
| 4 (A/B 归因)   | 1          | 6         |
| 5 (趋势预测)   | 1          | 6         |
| 6 (飞轮)       | 1,2,3,4,5  | F1-F4     |

### Agent Dispatch Summary

- **Wave 0**: 1 task — T1 → `quick`
- **Wave 1**: 2 tasks — T2 → `deep`, T3 → `deep`
- **Wave 2**: 2 tasks — T4 → `deep`, T5 → `deep`
- **Wave 3**: 1 task — T6 → `deep`
- **FINAL**: 4 tasks — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [x] 1. DB Migration Utility — `pipeline/db_migrate.py`

  **What to do**:
  - RED: 写测试 `tests/test_db_migrate.py`：(1) 对空表执行迁移后列存在, (2) 对已有列的表重复执行不报错, (3) 验证所有需要的列（PromptAsset.performance_score, PromptAsset.is_recommended, DeliveryVersion.auto_delivered, DeliveryVersion.client_signed_at）
  - GREEN: 实现 `pipeline/db_migrate.py`，函数 `run_migrations(engine)`:
    - 用 `inspect(engine).get_columns(table_name)` 检查列是否存在
    - 不存在则 `ALTER TABLE {table} ADD COLUMN {col} {type} DEFAULT {default}`
    - PromptAsset: `performance_score FLOAT DEFAULT NULL`, `is_recommended BOOLEAN DEFAULT 0`
    - DeliveryVersion: `auto_delivered BOOLEAN DEFAULT 0`, `client_signed_at DATETIME DEFAULT NULL`
  - REFACTOR: 确保幂等性，添加日志输出迁移动作
  - 在 `pipeline/models/prompt_asset.py` 中给 PromptAsset 类添加 `performance_score = Column(Float, nullable=True)` 和 `is_recommended = Column(Boolean, default=False)`
  - 在 `pipeline/models/delivery_version.py` 中给 DeliveryVersion 类添加 `auto_delivered = Column(Boolean, default=False)` 和 `client_signed_at = Column(DateTime, nullable=True)`

  **Must NOT do**: 不用 Alembic；不删除或重建已有表；不修改已有列

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**: Wave 0 (solo) | Blocks: 2,3,4,5,6 | Blocked By: None

  **References**:
  - `pipeline/models/prompt_asset.py` — 当前 PromptAsset 模型，需加 2 字段
  - `pipeline/models/delivery_version.py` — 当前 DeliveryVersion 模型，需加 2 字段
  - `sqlalchemy.inspect(engine).get_columns(table_name)` — 幂等检查
  - Tests fixture 模式 (A): engine+session

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_db_migrate.py -q` → PASS
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/ -q` → ≥456 passed, 0 failed

  **QA Scenarios:**

  ```
  Scenario: Fresh migration adds all 4 columns
    Tool: Bash (pytest)
    Steps: create_all() → run_migrations(engine) → inspect columns → assert performance_score, is_recommended, auto_delivered, client_signed_at exist
    Expected: All 4 new columns present
    Evidence: .sisyphus/evidence/task-1-fresh-migration.txt

  Scenario: Idempotent — double run no error
    Tool: Bash (pytest)
    Steps: run_migrations(engine) twice → no OperationalError
    Expected: Silent success, no duplicate columns
    Evidence: .sisyphus/evidence/task-1-idempotent.txt

  Scenario: Full regression
    Tool: Bash
    Steps: PYTHONPATH=. .venv/bin/pytest tests/ -q → ≥456 passed, 0 failed
    Evidence: .sisyphus/evidence/task-1-regression.txt
  ```

  **Commit**: `feat(db): add idempotent migration utility` | Files: db_migrate.py, prompt_asset.py, delivery_version.py, test_db_migrate.py

- [x] 2. 置信度评分路由 — `pipeline/orchestrator.py`

  **What to do**:
  - RED: 写测试 `tests/test_confidence_routing.py`：score≥80→pass, 50≤score<80→retry_alt_prompt, score<50→human_review, 边界值 80/50
  - GREEN: 在 `step_qa()` 中添加路由逻辑。提取独立方法 `_route_by_confidence(score: float) -> str` 返回 "pass"|"retry_alt_prompt"|"human_review"
  - 高置信度（≥80）：直接通过
  - 中置信度（50-79）：换 prompt 重试
  - 低置信度（<50）：标记 `needs_human_review=True`

  **Must NOT do**: 不删除已有 `_QA_MAX_RETRIES`/`_QA_PASS_THRESHOLD`；不超过 3 种策略；不改 QARecord 模型

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**: Wave 1 (with Task 3) | Blocks: 6 | Blocked By: 1

  **References**:
  - `pipeline/orchestrator.py:step_qa()` — 现有 retry 循环（`_QA_MAX_RETRIES=2`, `_QA_PASS_THRESHOLD=70`），新路由嵌入此处
  - `pipeline/orchestrator.py:step_generate()` — 理解 prompt 生成以支持"换 prompt"策略
  - `pipeline/models/qa_record.py:QARecord.score` — Float 字段，置信度数据源

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_confidence_routing.py -q` → PASS
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/ -q` → ≥456 passed, 0 failed

  **QA Scenarios:**

  ```
  Scenario: Routing correctness
    Tool: Bash (pytest)
    Steps: _route_by_confidence(85)=="pass", _route_by_confidence(65)=="retry_alt_prompt", _route_by_confidence(30)=="human_review"
    Evidence: .sisyphus/evidence/task-2-routing.txt

  Scenario: Boundary values
    Tool: Bash (pytest)
    Steps: 80.0→"pass", 79.9→"retry_alt_prompt", 50.0→"retry_alt_prompt", 49.9→"human_review"
    Evidence: .sisyphus/evidence/task-2-boundary.txt

  Scenario: Full regression
    Tool: Bash
    Steps: PYTHONPATH=. .venv/bin/pytest tests/ -q → ≥456 passed, 0 failed
    Evidence: .sisyphus/evidence/task-2-regression.txt
  ```

  **Commit**: `feat(qa): add confidence-based routing to step_qa` | Files: orchestrator.py, test_confidence_routing.py

- [x] 3. 品类知识匿名化 — `pipeline/layers/knowledge_anonymizer.py`

  **What to do**:
  - RED: 测试 `tests/test_knowledge_anonymizer.py`：品牌名→`[BRAND]`、订单号→`[ORDER_ID]`、路径→`[PATH]`、混合文本、无敏感信息不变
  - GREEN: 新建 `pipeline/layers/knowledge_anonymizer.py`：
    - `anonymize_knowledge(entry: KnowledgeEntry, brand_list: list[str]) -> KnowledgeEntry` — regex 替换，返回副本
    - 模式：品牌名（动态 brand_list）、订单号（`#?ORD-\d+`）、路径（`/[\w/]+\.\w+`）
  - 单向不可逆，纯函数无副作用

  **Must NOT do**: 不建反查表；不改 KnowledgeEntry 模型

  **Recommended Agent Profile**: `deep` | **Skills**: []
  **Parallelization**: Wave 1 (with Task 2) | Blocks: 6 | Blocked By: 1

  **References**:
  - `pipeline/models/knowledge_entry.py` — 字段：id, tenant_id, source_project_id, category, title, content, tags, usage_count, created_at

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_knowledge_anonymizer.py -q` → PASS
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/ -q` → ≥456 passed, 0 failed

  **QA Scenarios:**

  ```
  Scenario: Brand/order/path anonymized, clean text unchanged
    Tool: Bash (pytest)
    Steps: "Nike #ORD-123 /data/img.png" + brand_list=["Nike"] → no "Nike", no "#ORD-123", no "/data/img.png" in result; "通用说明" → unchanged
    Evidence: .sisyphus/evidence/task-3-anonymize.txt
  ```

  **Commit**: `feat(knowledge): add anonymization for cross-client sharing` | Files: knowledge_anonymizer.py, test_knowledge_anonymizer.py

- [ ] 4. A/B 归因引擎 — `pipeline/layers/ab_attribution.py`

  **What to do**:
  - RED: 测试 `tests/test_ab_attribution.py`：CSV/JSON 导入、`performance_score = 0.6*CTR + 0.4*CVR`、≥0.75→is_recommended=True、<0.75→False、边界值、无效数据
  - GREEN: 新建 `pipeline/layers/ab_attribution.py`：
    - `import_performance_data(file_path, format="csv") -> list[dict]`
    - `calculate_performance_score(ctr, cvr) -> float` — `0.6*ctr + 0.4*cvr`
    - `apply_attribution(session, data) -> int` — 批量更新 PromptAsset
    - 常量：`CTR_WEIGHT=0.6`, `CVR_WEIGHT=0.4`, `RECOMMEND_THRESHOLD=0.75`

  **Must NOT do**: 不指定供应商 API；不改 PromptAsset 模型（Task 1 已加）；不引入 pandas

  **Recommended Agent Profile**: `deep` | **Skills**: []
  **Parallelization**: Wave 2 (with Task 5) | Blocks: 6 | Blocked By: 1

  **References**:
  - `pipeline/models/prompt_asset.py` — Task 1 新增的 performance_score, is_recommended
  - `docs/data-flow.md` — performance_score 字段定义
  - `docs/L5_REQUIREMENTS.md` — 归因引擎规格

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_ab_attribution.py -q` → PASS
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/ -q` → ≥456 passed, 0 failed

  **QA Scenarios:**

  ```
  Scenario: CSV import + score + threshold
    Tool: Bash (pytest)
    Steps: CSV(ctr=0.8, cvr=0.6) → score=0.72 → is_recommended=False; CSV(ctr=0.9, cvr=0.8) → score=0.86 → is_recommended=True
    Evidence: .sisyphus/evidence/task-4-attribution.txt

  Scenario: Invalid data → ValueError
    Tool: Bash (pytest)
    Steps: CSV missing "cvr" → raises ValueError
    Evidence: .sisyphus/evidence/task-4-invalid.txt
  ```

  **Commit**: `feat(attribution): add A/B attribution engine` | Files: ab_attribution.py, test_ab_attribution.py

- [ ] 5. 趋势预测引擎（Wave 2，与 Task 4 并行）

  **What to do**:
  - 新建 `pipeline/models/trend_forecast.py`：TrendForecast model（id, tenant_id, asin, category, period_start, period_end, predicted_trend: str enum ["rising","stable","declining"], confidence: Float, data_points: JSON, created_at）
  - 新建 `pipeline/layers/trend_engine.py`：
    - `analyze_trend(asin, keepa_data: dict) -> TrendForecast` — 接收 `amazon_data.py` 已有的 Keepa 价格/排名历史数据
    - 算法：取最近 30/60/90 天数据点，线性回归斜率判断趋势方向，R² 作为 confidence
    - 若数据点 < 7 天，返回 `confidence=0.0, predicted_trend="stable"`（数据不足 fallback）
  - 新建 `tests/test_trend_engine.py`（TDD）：
    - RED: 上升趋势（递增价格序列 → "rising", confidence > 0.7）
    - RED: 下降趋势（递减排名序列 → "declining"）
    - RED: 平稳趋势（波动 < 5% → "stable"）
    - RED: 数据不足（< 7 天 → fallback）
    - RED: 空数据 → 抛 ValueError
    - GREEN: 实现 `trend_engine.py`
    - REFACTOR: 提取阈值为常量
  - 在 `pipeline/db_migrate.py` 的 `MIGRATIONS` 列表中追加 trend_forecast 表创建（通过 Task 1 的 `create_all()` 机制自动处理新表）

  **Must NOT do**:
  - 不修改 `amazon_data.py`
  - 不引入 numpy/scipy 等重型依赖（纯 Python 标准库 statistics 模块即可）
  - 不加 API 端点

  **Recommended Agent Profile**: `deep` | **Skills**: []
  **Parallelization**: Wave 2 (with Task 4) | Blocks: 6 | Blocked By: 1

  **References**:
  - `pipeline/layers/amazon_data.py` — Keepa 数据结构（只读参考，了解 price_history/rank_history 字段格式）
  - `pipeline/models/qa_record.py` — 参考 Float score 字段模式
  - `docs/L5_REQUIREMENTS.md` — 趋势预测规格
  - `tests/test_knowledge_anonymizer.py` 或 `tests/test_ab_attribution.py` — 测试 fixture 模式参考

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_trend_engine.py -q` → PASS (≥5 tests)
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/ -q` → ≥456 passed, 0 failed

  **QA Scenarios:**

  ```
  Scenario: Rising trend detection
    Tool: Bash (pytest)
    Steps: 输入 30 天递增价格序列 [10,11,12,...,39] → predicted_trend="rising", confidence>0.7
    Evidence: .sisyphus/evidence/task-5-rising.txt

  Scenario: Insufficient data fallback
    Tool: Bash (pytest)
    Steps: 输入 3 天数据 → predicted_trend="stable", confidence=0.0
    Evidence: .sisyphus/evidence/task-5-fallback.txt

  Scenario: Empty data → ValueError
    Tool: Bash (pytest)
    Steps: 输入空 dict → raises ValueError
    Evidence: .sisyphus/evidence/task-5-empty-error.txt
  ```

  **Commit**: `feat(trend): add trend forecast engine using Keepa data` | Files: trend_engine.py, trend_forecast.py, test_trend_engine.py

- [x] 6. 全自动飞轮（Wave 3，依赖 Task 1-5 全部完成）

  **What to do**:
  - 在 `pipeline/config.py` 的 Config dataclass 中新增字段：
    - `flywheel_enabled: bool = field(default_factory=lambda: os.getenv("AIP_FLYWHEEL_ENABLED","false").lower()=="true")` — 总开关
    - `flywheel_auto_deliver: bool = field(default_factory=lambda: os.getenv("AIP_FLYWHEEL_AUTO_DELIVER","false").lower()=="true")`
    - `flywheel_confidence_threshold: float = field(default_factory=lambda: float(os.getenv("AIP_FLYWHEEL_CONFIDENCE_THRESHOLD","85")))` — 自动交付的最低置信度
  - 在 `pipeline/models/delivery_version.py` 的 DeliveryVersion model 中新增列：
    - `auto_delivered: bool = Column(Boolean, default=False)` — 是否由飞轮自动交付
    - `client_signed_at: datetime = Column(DateTime, nullable=True)` — 客户签收时间
  - 在 `pipeline/db_migrate.py` 的 `MIGRATIONS` 列表中追加这两个新列的 ALTER TABLE
  - 新建 `pipeline/flywheel.py`：
    - `run_flywheel(project_id, session) -> dict` — 飞轮主流程：
      1. 检查 `config.flywheel_enabled`，未开启则 `return {"skipped": True, "reason": "disabled"}`
      2. 调用 orchestrator 的 `step_init → ... → step_qa` 获取 QA 分数
      3. 若 QA score ≥ `flywheel_confidence_threshold` 且 `flywheel_auto_deliver=True`：自动创建 DeliveryVersion（`auto_delivered=True`），返回 `{"auto_delivered": True, "score": N}`
      4. 若 QA score < threshold：返回 `{"auto_delivered": False, "score": N, "reason": "below_threshold"}`
    - `check_flywheel_status(config) -> dict` — 返回飞轮配置状态（方便 CLI 查看）
  - 新建 `tests/test_flywheel.py`（TDD）：
    - RED: flywheel_enabled=False → skipped
    - RED: QA score ≥ threshold + auto_deliver=True → auto_delivered=True
    - RED: QA score < threshold → auto_delivered=False
    - RED: auto_deliver=False（但 enabled=True）→ 不自动交付，只返回 score
    - RED: check_flywheel_status 返回正确配置字典
    - GREEN: 实现 flywheel.py
    - REFACTOR: 确保 orchestrator 调用是 mock 的，不依赖真实 pipeline
  - **集成点**：在 `orchestrator.py` 的 `step_deliver()` 末尾添加飞轮触发入口（可选调用，受 config flag 控制）

  **Must NOT do**:
  - 不加调度器（cron/celery）
  - 不加 API 端点
  - 飞轮默认关闭，必须显式 env var 开启
  - 不修改 `step_qa()` 本身的逻辑（置信度路由已由 Task 2 处理）

  **Recommended Agent Profile**: `deep` | **Skills**: []
  **Parallelization**: Wave 3 (sequential, after all) | Blocks: none | Blocked By: 1, 2, 3, 4, 5

  **References**:
  - `pipeline/orchestrator.py:step_deliver()` — 飞轮触发入口位置
  - `pipeline/config.py` — Config dataclass 模式（env var + default）
  - `pipeline/models/delivery_version.py` — DeliveryVersion 现有字段
  - `pipeline/orchestrator.py:step_qa()` — Task 2 置信度路由逻辑（参考 score 获取方式）
  - `tests/test_confidence_routing.py` — mock orchestrator 步骤的测试模式参考

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_flywheel.py -q` → PASS (≥5 tests)
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/ -q` → ≥456 passed, 0 failed
  - [ ] `AIP_FLYWHEEL_ENABLED=false PYTHONPATH=. python -c "from pipeline.flywheel import run_flywheel; print('import ok')"` → 无报错

  **QA Scenarios:**

  ```
  Scenario: Flywheel disabled → skip
    Tool: Bash (pytest)
    Steps: config.flywheel_enabled=False → run_flywheel() returns {"skipped": True}
    Evidence: .sisyphus/evidence/task-6-disabled.txt

  Scenario: High score + auto_deliver → auto delivery
    Tool: Bash (pytest)
    Steps: mock step_qa score=90, threshold=85, auto_deliver=True → DeliveryVersion created with auto_delivered=True
    Evidence: .sisyphus/evidence/task-6-auto-deliver.txt

  Scenario: Low score → no delivery
    Tool: Bash (pytest)
    Steps: mock step_qa score=60, threshold=85 → auto_delivered=False, reason="below_threshold"
    Evidence: .sisyphus/evidence/task-6-below-threshold.txt
  ```

  **Commit**: `feat(flywheel): add configurable auto-trigger pipeline` | Files: flywheel.py, config.py, delivery_version.py, test_flywheel.py

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [ ] F1. **Plan Compliance Audit** — `oracle`
      Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
      Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
      Run `PYTHONPATH=. .venv/bin/pytest tests/ -q` + type check. Review all changed files for: `as any`, empty catches, print in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names.
      Output: `Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
      Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration. Test edge cases: empty DB, invalid input, repeated migration runs. Save to `.sisyphus/evidence/final-qa/`.
      Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
      For each task: read "What to do", read actual diff (git log/diff). Verify 1:1 — everything in spec was built, nothing beyond spec was built. Check "Must NOT do" compliance. Flag unaccounted changes.
      Output: `Tasks [N/N compliant] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

| Wave | Commit Message                                                           | Files                                                         | Pre-commit       |
| ---- | ------------------------------------------------------------------------ | ------------------------------------------------------------- | ---------------- |
| 0    | `feat(db): add idempotent migration utility`                             | db_migrate.py, test_db_migrate.py                             | pytest tests/ -q |
| 1a   | `feat(qa): add confidence-based routing to step_qa`                      | orchestrator.py, test_confidence_routing.py                   | pytest tests/ -q |
| 1b   | `feat(knowledge): add anonymization for cross-client sharing`            | knowledge_anonymizer.py, test_knowledge_anonymizer.py         | pytest tests/ -q |
| 2a   | `feat(attribution): add A/B attribution engine with performance scoring` | ab_attribution.py, prompt_asset.py, test_ab_attribution.py    | pytest tests/ -q |
| 2b   | `feat(trend): add trend forecast engine using Keepa data`                | trend_engine.py, trend_forecast.py, test_trend_engine.py      | pytest tests/ -q |
| 3    | `feat(flywheel): add configurable auto-trigger pipeline`                 | flywheel.py, config.py, delivery_version.py, test_flywheel.py | pytest tests/ -q |

---

## Success Criteria

### Verification Commands

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q  # Expected: ≥456 passed, 0 failed
```

### Final Checklist

- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All 456+ tests pass
- [ ] Each feature independently toggleable
- [ ] DB migration idempotent (run twice, no error)
