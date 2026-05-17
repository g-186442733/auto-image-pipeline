# CHANGELOG

本项目所有重要变更将记录在本文件中。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [v1.2] - 2026-04-19

### L4/L5 建设完成（Tasks 1-6）

本轮完成 L4/L5 全部 6 个新模块的实现，系统正式具备置信度路由、A/B 归因、趋势预测和全自动飞轮能力。测试基线：51 passed（核心新增模块），整体基线参见各模块 `tests/` 目录说明。

#### DB Migration（Task 1）

- 新增 `pipeline/db_migrate.py`：幂等数据库迁移工具，用 `inspect()` 检查列存在后再执行 `ALTER TABLE`
- 新增列：
  - `prompt_assets.performance_score (FLOAT DEFAULT NULL)`
  - `prompt_assets.is_recommended (BOOLEAN DEFAULT 0)`
  - `delivery_versions.auto_delivered (BOOLEAN DEFAULT 0)`
  - `delivery_versions.client_signed_at (DATETIME DEFAULT NULL)`
- 入口：`run_migrations(engine)`，幂等可重复执行

#### 置信度路由（Task 2）

- `pipeline/orchestrator.py` 的 `step_qa` 新增三档分流逻辑：
  - HIGH（≥ 80）：自动通过，无需人工介入
  - MID（50~79）：快审，推送人工确认
  - LOW（< 50）：进入完整 QA 流程

#### 知识库匿名化（Task 3）

- 新增 `pipeline/layers/knowledge_anonymizer.py`
- `anonymize_knowledge(entry, brand_list)`：移除品牌名、订单号（`ORD-\d+`）、文件路径等敏感标识
- 批量处理：外部通过列表推导或 `map()` 调用单条接口

#### A/B 归因（Task 4）

- 新增 `pipeline/layers/ab_attribution.py`
- `import_performance_data(file_path, format)`：支持 CSV/JSON 格式导入，校验必要字段
- `calculate_performance_score(ctr, cvr)`：`0.6×CTR + 0.4×CVR`，阈值 ≥ 0.75 → `is_recommended=True`
- `apply_attribution(session, data)`：批量写入 `prompt_assets.performance_score` / `is_recommended`
- ORM 修复：`session.query().get()` 迁移至 `session.get()`（SQLAlchemy 2.x 兼容）

#### 趋势预测（Task 5）

- 新增 `pipeline/layers/trend_engine.py`
- `analyze_trend(asin, keepa_data)`：纯 Python `statistics` 模块线性回归，无外部依赖
- 数据点 < 7 时降级返回 `stable + confidence=0.0`
- 输出：`{"predicted_trend": "rising"|"stable"|"declining", "confidence": float, "data_points": int}`

#### 全自动飞轮（Task 6）

- 新增 `pipeline/flywheel.py`
- `run_flywheel(project_id, session, config, qa_score, qa_score_fn)`：QA 分达阈值时自动创建新 `DeliveryVersion`
- `check_flywheel_status(config)`：查询当前飞轮配置状态
- 三重 env flag 控制：`flywheel_enabled`、`flywheel_auto_deliver`、`flywheel_confidence_threshold`，默认全部关闭
- 跳过路径返回 `{"skipped": True}`，自动交付路径写库并记录日志

#### ORM 修复（commit dbf3b47）

- `PromptAsset`：补充 `performance_score = Column(Float)`、`is_recommended = Column(Boolean)`
- `DeliveryVersion`：补充 `client_signed_at = Column(DateTime)`
- `ab_attribution.py`：将 legacy `session.query().get()` 替换为 `session.get()`

---

## [v1.1] - 2026-04-19

### 文档一致性复审修复（4 份基准文档）

本轮聚焦：4 份基准文档（PRD / SYSTEM_SPEC / TEST_CASES / L5_REQUIREMENTS）写完后的交叉一致性复审，共发现并修复 **8 项不一致问题**（3 P0 + 3 P1 + 2 P2）。代码未变动，**测试基线保持 417 passed / 0 failed**。

#### 🔴 P0 阻塞级修复

- **标签体系两套命名互不兼容（A 方案锁定）**
  - `docs/SYSTEM_SPEC.md` §5 重写为路线图三层独立维度：
    - **Function**：`FUNC_HERO` / `FUNC_BENEFIT` / `FUNC_LIFESTYLE` / `FUNC_DETAIL` / `FUNC_SOCIAL` / `FUNC_SIZE`
    - **Intent**：`INT_01`（性价比） / `INT_02`（高端） / `INT_03`（便捷） / `INT_04`（专业） / `INT_05`（情绪） / `INT_06`（礼赠）
    - **Role**：`ROLE_01`（产品主体） ~ `ROLE_07`（信任背书）
    - **Slot**：`MAIN` / `PT01` ~ `PT07`
  - 末尾追加「迁移说明」指向 L5 S1 代码重构（`pipeline/constants/tags.py` 待重命名，本轮未动代码）
- **KPI 数字打架修复**：`docs/PRD.md` §8 行 342 `点击率提升 > 70%` → `≥ 60%`，与 `L5_REQUIREMENTS.md` 跃迁条件保持一致

#### 🟡 P1 修复

- **LoRA 状态归属厘清**
  - `docs/PRD.md` §3.3 末尾新增「L4 实施状态」6 项表格，明确「品牌 LoRA」状态 = ❌ 未实现
  - `docs/L5_REQUIREMENTS.md` §1.1 跃迁条件追加「品牌 LoRA 生产化 ≥ 3 客户在用」硬指标
- **交叉引用断链修复**：`docs/L5_REQUIREMENTS.md` §10
  - 表内引用 `§10.2 ~ 10.5` → `§10 第 2 ~ 5 项`
  - 趋势引擎 → `PRD §3.4 + §12.9`
  - LoRA 品牌锁 → `PRD §3.3`
  - `TEST_CASES.md` §7 第 ⑧ 项 `（L5 待补）` → `（测试待补）`
- **测试清单不一致**：`docs/TEST_CASES.md` §10 新增第 7 项 `test_l5_migration.py`

#### 🟢 P2 修复

- `docs/SYSTEM_SPEC.md` §7 开头新增 L5 外部依赖前瞻段（Redis / Celery / Stripe），并指向 `L5_REQUIREMENTS.md` §6
- `docs/L5_REQUIREMENTS.md` §5 新增第 8 项 `test_knowledge_base_anonymization.py`（覆盖 PRD §4.6 F-DRL-05）
- `docs/TEST_CASES.md` §8 阶段二→阶段三补「2+ 品类互通的覆盖率断言」占位

### 文档版本号统一

- `PRD.md`：v1.0 → **v1.1**
- `SYSTEM_SPEC.md`：1.0 → **v1.1**
- `TEST_CASES.md`：（无版本号）→ **v1.1**
- `L5_REQUIREMENTS.md`：（无版本号）→ **v1.1**

### 未变更

- 代码（`pipeline/`、`tests/`）：未动
- 测试基线：417 passed / 0 failed（未运行回归，因无代码变更）
- ORM Schema：未变（27 张表）
- L5 S1 实际开发（Tenant 表 / tenant_id 回填 / `pipeline/constants/tags.py` 重命名）：**待启动**

### 路线图阶段-编排等级对照（4 份文档已统一）

| 阶段   | 编排等级      | 时间窗  | 核心能力             |
| ------ | ------------- | ------- | -------------------- |
| 阶段一 | L2 多工具并行 | 0-3 月  | 三层标签 + 11 步出图 |
| 阶段二 | L3 事件驱动   | 3-6 月  | Fan-out 三引擎       |
| 阶段三 | L4 Loop 闭环  | 6-12 月 | LoRA + 自动质检      |
| 阶段四 | L5 自主决策   | 12 月+  | 趋势预测 + SaaS 飞轮 |

---

## [v1.0] - 2026-04-19

### 新增

- 4 份基准文档首版完成：
  - `docs/PRD.md`（产品需求文档，覆盖 L1~L5）
  - `docs/SYSTEM_SPEC.md`（系统规范，1066+ 行）
  - `docs/TEST_CASES.md`（测试用例规范，214 行，对应 417 测试基线）
  - `docs/L5_REQUIREMENTS.md`（L5 专项需求，336 行）
- 文档基准源：`AI设计服务进化路线图.md`（1766 行，已全文消化）
- 阶段-编排等级映射表统一：阶段一=L2 / 阶段二=L3 / 阶段三=L4 / 阶段四=L5
