# SaaS 多租户迁移 + 品牌体系重构

## TL;DR

> **Quick Summary**: 将 auto-image-pipeline 从单租户 SQLite 应用迁移为多租户 PostgreSQL SaaS 架构。包含：PostgreSQL 迁移、用户认证、全表 tenant_id 强制、路由层租户隔离、品牌三级拆分、品牌自动更新、LoRA 清理。
>
> **Deliverables**:
>
> - PostgreSQL 数据库替换 SQLite
> - User 模型 + session-based 认证（email/password，无 OAuth）
> - 34 张表全部 tenant_id NOT NULL + 路由层租户隔离
> - Customer→Brand→Product 三级品牌体系（替换现有 1:1 BrandProfile）
> - 品牌自动更新（F-BP-06）
> - 价格带定位分析（F-DA-07）
> - 三引擎 Fan-out 查询（F-GEN-06）
> - 反馈转译（F-DEL-03）
> - ADR-011 修改（去除 LoRA 门控）
> - 所有 LoRA 占位字段和引用清除
>
> **Estimated Effort**: Large
> **Parallel Execution**: YES - 5 waves
> **Critical Path**: Task 1 → Task 3 → Task 5 → Task 8 → F1-F4

---

## Context

### Original Request

用户要求实现所有 PRD 和 ADR 中规划但未完成的功能（LoRA 除外），使系统达到 SaaS 化可用状态。

### Interview Summary

**Key Discussions**:

- LoRA 全部跳过，用闭源模型出图
- schema 约束已解除，允许改数据库结构
- 测试策略：简单测试，关键路径写几个
- 不修改 `/input/new`、`/input/<id>/edit`、`customer_input.html`

**Research Findings**:

- 34 张表，26 有 nullable tenant_id，7 缺失，Tenant 模型已存在但从未使用
- 无认证系统（无 User 模型、无 login/logout）
- BrandProfile 10 维度完整但只 1:1 挂在 Project 下
- 6 个模型未在 `__init__.py` 导出
- Flask app.py 1112 行，30+ 路由，4 Blueprint

### Metis Review

**Identified Gaps** (addressed):

- PostgreSQL 应提前到 Wave 1（SQLite ALTER TABLE 限制多）→ 已采纳
- Auth scope 需锁定（session-based, email/password, 无 OAuth/RBAC）→ 已设定
- 品牌三级拆分需明确维度归属 → 标记为 DECISION NEEDED
- 文件存储需考虑租户隔离 → 加入 guardrails
- 每个 Wave 结束后 app 必须可运行 → 已设定

---

## Work Objectives

### Core Objective

将单租户 SQLite 应用迁移为多租户 PostgreSQL SaaS 架构，实现用户认证、租户隔离和品牌体系重构。

### Concrete Deliverables

- PostgreSQL 数据库（替换 SQLite）
- `/login`、`/logout` 路由 + `@login_required` 装饰器
- 34 张表 tenant_id NOT NULL + `@tenant_required` 装饰器
- CustomerProfile → BrandProfile → ProductProfile 三级体系
- F-BP-06 品牌自动更新逻辑
- ADR-011 修改文档
- 零 LoRA 引用

### Definition of Done

- [ ] `python -c "from sqlalchemy import create_engine; e=create_engine('postgresql://...'); e.connect()"` 成功
- [ ] 登录/登出端到端可用
- [ ] 租户 A 创建的数据，租户 B 无法看到
- [ ] 品牌三级 CRUD 可用，prompt 注入仍正常
- [ ] `grep -ri "lora" --include="*.py" --include="*.html" | wc -l` 返回 0
- [ ] 所有 pytest 通过

### Must Have

- PostgreSQL 连接替换 SQLite
- email/password session-based 认证
- 全表 tenant_id NOT NULL 约束
- 路由层租户隔离（装饰器模式）
- 品牌三级拆分数据迁移
- 每个 Wave 结束后 app 可正常启动

### Must NOT Have (Guardrails)

- ❌ OAuth/RBAC/角色权限（只做简单 email/password + 租户隔离）
- ❌ 租户管理 UI（只通过 DB 创建租户）
- ❌ Schema-per-tenant 多租户模式（用 row-level tenant_id）
- ❌ 修改 `/input/new`、`/input/<id>/edit`、`customer_input.html`
- ❌ 引入 Alembic（继续用 `db_migrate.py` 手工迁移）
- ❌ 任何 LoRA 功能
- ❌ 重构 app.py 路由结构（本次不做拆分）
- ❌ 连接池、读写分离等 PG 高级特性
- ❌ 品牌模板/继承/版本管理等扩展功能

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed.

### Test Decision

- **Infrastructure exists**: NO（需要搭建）
- **Automated tests**: YES (Tests-after, 关键路径)
- **Framework**: pytest
- **Test scope**: 认证流程、租户隔离、品牌层级 CRUD

### QA Policy

Every task includes agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **API/Routes**: Bash (curl) - 发请求、验证状态码和响应
- **DB Schema**: Bash (python -c) - 验证表结构和约束
- **Data Isolation**: Bash (curl + python) - 跨租户查询验证

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately - foundation):
├── Task 1: PostgreSQL 迁移 [deep]
├── Task 2: 修复 models/__init__.py 导出 [quick]
└── Task 3: pytest 基础设施搭建 [quick]

Wave 2 (After Wave 1 - auth + schema):
├── Task 4: User 模型 + 认证系统 [deep]
├── Task 5: 7 张表补 tenant_id + 全表 backfill + NOT NULL [unspecified-high]
└── Task 6: 确认 6 个未导出模型是否实际使用 + 清理 [quick]

Wave 3 (After Wave 2 - tenant isolation + brand):
├── Task 7: 路由层租户隔离装饰器 [deep]
├── Task 8: 品牌三级拆分 Customer→Brand→Product [ultrabrain]
└── Task 9: 文件存储路径租户隔离 [unspecified-high]

Wave 4 (After Wave 3 - features + cleanup):
├── Task 10: 品牌自动更新 F-BP-06 [unspecified-high]
├── Task 11: ADR-011 修改（去除 LoRA 门控）[quick]
├── Task 12: LoRA 占位字段全面清理 [quick]
├── Task 13: 价格带定位分析 F-DA-07 [deep]
├── Task 14: 三引擎 Fan-out 查询 F-GEN-06 [deep]
└── Task 15: 反馈转译 F-DEL-03 [unspecified-high]

Wave FINAL (After ALL tasks):
├── F1: Plan compliance audit (oracle)
├── F2: Code quality review (unspecified-high)
├── F3: Real QA (unspecified-high)
└── F4: Scope fidelity check (deep)
-> Present results -> Get explicit user okay
```

### Dependency Matrix

| Task | Depends On | Blocks      | Wave |
| ---- | ---------- | ----------- | ---- |
| 1    | -          | 4,5,6,7,8,9 | 1    |
| 2    | -          | 4,5,6       | 1    |
| 3    | -          | 4           | 1    |
| 4    | 1,2,3      | 7           | 2    |
| 5    | 1,2        | 7,8         | 2    |
| 6    | 1,2        | -           | 2    |
| 7    | 4,5        | 10          | 3    |
| 8    | 4,5        | 10          | 3    |
| 9    | 5          | -           | 3    |
| 10   | 7,8        | F1-F4       | 4    |
| 11   | 7          | F1-F4       | 4    |
| 12   | 7          | F1-F4       | 4    |
| 13   | 8          | F1-F4       | 4    |
| 14   | 7          | F1-F4       | 4    |
| 15   | 7,8        | F1-F4       | 4    |

### Agent Dispatch Summary

- **Wave 1**: 3 tasks — T1→`deep`, T2→`quick`, T3→`quick`
- **Wave 2**: 3 tasks — T4→`deep`, T5→`unspecified-high`, T6→`quick`
- **Wave 3**: 3 tasks — T7→`deep`, T8→`ultrabrain`, T9→`unspecified-high`
- **Wave 4**: 6 tasks — T10→`unspecified-high`, T11→`quick`, T12→`quick`, T13→`deep`, T14→`deep`, T15→`unspecified-high`
- **FINAL**: 4 tasks — F1→`oracle`, F2→`unspecified-high`, F3→`unspecified-high`, F4→`deep`

---

## TODOs

### Wave 1 — Foundation

- [x] **Task 1**: PostgreSQL 迁移 — 安装 PG via brew，创建本地 DB，安装 psycopg2-binary，更新 config.py / base.py / .env，迁移 SQLite 数据到 PG，更新 db_migrate.py 兼容 PG，确保 app 启动
- [x] **Task 2**: 修复 models/**init**.py 导出 — 补充 DecisionLog、FeedbackAction、ContentAsset、Hypothesis、PipelineRun、TrendForecast 的 import 和 **all**
- [x] **Task 3**: pytest 基础设施搭建 — 创建/更新 conftest.py 支持测试用 PG DB，确保 `pytest --collect-only` 不报错

### Wave 2 — Auth + Schema

- [x] **Task 4**: User 模型 + 认证系统 — 新建 User 模型（id/email/password_hash/tenant_id/created_at），/login /logout 路由，@login_required 装饰器，session auth，关键路径 pytest
- [x] **Task 5**: 7 张表补 tenant_id — customer_briefs、decision_logs、feedback_actions、content_assets、hypotheses、pipeline_runs、trend_forecasts 加 tenant_id 列，backfill，NOT NULL 约束，db_migrate.py 更新
- [x] **Task 6**: 确认 6 个未导出模型实际使用情况 + 清理 — 检查 DecisionLog/FeedbackAction/ContentAsset/Hypothesis/PipelineRun/TrendForecast 是否在路由或 layers 中被引用，确认后清理死代码

### Wave 3 — Tenant Isolation + Brand

- [x] **Task 7**: 路由层租户隔离装饰器 — @tenant_required 装饰器，从 session 读取 tenant_id，在所有 DB 查询加 .filter_by(tenant_id=...) 过滤，保护所有非 login 路由
- [x] **Task 8**: 品牌三级拆分 Customer→Brand→Product — 新建 CustomerProfile / ProductProfile 模型，BrandProfile 挂在 Brand 下，数据迁移，更新 brand_profiler.py / prompt_engine.py / input_layer.py，CRUD 路由
- [x] **Task 9**: 文件存储路径租户隔离 — 所有 output_dir / image_output_dir 路径加 tenant_id 子目录前缀，确保跨租户文件不相互访问

### Wave 4 — Features + Cleanup

- [x] **Task 10**: 品牌自动更新 F-BP-06 — feedback_loop.py 接入 Web 触发（POST /brand/auto-update），update_brand_profile_from_results() 挂钩到 QA 完成事件
- [x] **Task 11**: ADR-011 修改 — 更新 docs/adr/ADR-011-brand-lora-as-l5-gate.md，标记为 SUPERSEDED，说明 LoRA 门控去除原因
- [x] **Task 12**: LoRA 占位字段全面清理 — 从所有 .py 和 .html 文件删除 lora_type、parent_category_lora_id 字段及引用，验证 grep 为 0
- [x] **Task 13**: 价格带定位分析 F-DA-07 — 同价位段竞品视觉调性基线分析模块，新建 price_band_analyzer.py，集成到 PriceAnalysis 流程，提供 /api/price-band-analysis 端点
- [x] **Task 14**: 三引擎 Fan-out 查询 F-GEN-06 — 引擎 A/B/C 并行查询，汇总推荐报告，新建 fanout_engine.py，提供 /api/fanout-query 端点
- [x] **Task 15**: 反馈转译 F-DEL-03 — 客户模糊反馈 → 可执行变量修改指令，新建 feedback_translator.py，/api/translate-feedback 端点

---

## Final Verification Wave

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [x] F1. **Plan Compliance Audit** — `oracle`
      Read the plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files in `.sisyphus/evidence/`. Compare deliverables against plan.
      Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality Review** — `unspecified-high`
      Run linter + `pytest`. Review all changed files for: `as any`/`@ts-ignore` equivalent, empty excepts, print() in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction.
      Output: `Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [x] F3. **Real Manual QA** — `unspecified-high`
      Start from clean state. Execute EVERY QA scenario from EVERY task. Test cross-task integration. Test edge cases: empty state, invalid input, wrong tenant. Save to `.sisyphus/evidence/final-qa/`.
      Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [x] F4. **Scope Fidelity Check** — `deep`
      For each task: read "What to do", read actual diff. Verify 1:1. Check "Must NOT do" compliance. Detect cross-task contamination. Flag unaccounted changes.
      Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

| Wave | Commit Message                                                          | Pre-commit                  |
| ---- | ----------------------------------------------------------------------- | --------------------------- |
| 1    | `feat(db): migrate from SQLite to PostgreSQL`                           | app starts                  |
| 1    | `fix(models): export all missing models in __init__.py`                 | imports pass                |
| 1    | `chore(test): set up pytest infrastructure`                             | pytest runs                 |
| 2    | `feat(auth): add User model + login/logout + session auth`              | pytest tests/test_auth.py   |
| 2    | `feat(db): add tenant_id to all tables, backfill, enforce NOT NULL`     | app starts                  |
| 3    | `feat(tenant): add @tenant_required decorator + apply to all routes`    | pytest tests/test_tenant.py |
| 3    | `feat(brand): split BrandProfile into Customer/Brand/Product hierarchy` | pytest tests/test_brand.py  |
| 3    | `feat(storage): add tenant-scoped file paths`                           | app starts                  |
| 4    | `feat(brand): implement brand auto-update F-BP-06`                      | pytest                      |
| 4    | `feat(analysis): add price-band positioning analysis F-DA-07`           | pytest                      |
| 4    | `feat(gen): add tri-engine fan-out query F-GEN-06`                      | pytest                      |
| 4    | `feat(feedback): add feedback translation F-DEL-03`                     | pytest                      |
| 4    | `docs(adr): modify ADR-011 to remove LoRA gate`                         | -                           |
| 4    | `chore: remove all LoRA placeholder fields and references`              | grep lora = 0               |

---

## Success Criteria

### Verification Commands

```bash
# PostgreSQL 连接
python -c "from pipeline.models.base import engine; print(engine.url)"  # Expected: postgresql://...

# 认证
curl -X POST http://localhost:9010/login -d '{"email":"admin@test.com","password":"test123"}' -c cookies.txt  # Expected: 200
curl http://localhost:9010/projects -b cookies.txt  # Expected: 200 with tenant-filtered data
curl http://localhost:9010/projects  # Expected: 401 or redirect to login

# 租户隔离
# (用两个不同 tenant 的 cookie 验证)

# 品牌层级
curl http://localhost:9010/api/customers -b cookies.txt  # Expected: 200 with customer list
curl http://localhost:9010/api/brands -b cookies.txt  # Expected: 200 with brand list

# LoRA 清除
grep -ri "lora" --include="*.py" --include="*.html" pipeline/ | wc -l  # Expected: 0

# 测试
pytest --tb=short  # Expected: all pass
```

### Final Checklist

- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All tests pass
- [ ] App starts and serves all routes on PostgreSQL
- [ ] No SQLite references in production code
- [ ] No LoRA references anywhere
