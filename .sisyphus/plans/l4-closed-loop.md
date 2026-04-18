# L4 闭环系统 — 完整实施计划

## TL;DR

> **Quick Summary**: 实现 auto-image-pipeline 从 L3（流水线）到 L4（闭环）的跃迁。17 项任务覆盖：客户输入 UI、品牌画像卡、A+ 内容生成、三层标签、Reference Pack、一致性系统、5 硬门 QA、交付包、客户反馈 UI、版本管理、修改决策表、Prompt 编辑 UI、ASIN 追踪、主图变更检测、跨项目知识库、ImageSlot 清理。
>
> **Deliverables**:
>
> - 引导式客户输入 UI（5 组必问 + 5 组建议问）
> - 素材上传 UI（拖拽上传 + 预览）
> - 品牌画像卡 UI（10 维度展示 + 编辑）
> - A+ 内容生成逻辑（7 模块 storyboard）
> - 三层标签体系（intent/role/scene + layer 函数）
> - Reference Pack（6 组件：mood_board / color_palette / typography / layout_ref / material_texture / competitor_ref）
> - 一致性系统（5 变量锁定）
> - QA Gate 5 硬门完整实现
> - 交付包完善（5 样东西）
> - 客户反馈 UI + 反馈驱动修改
> - 版本管理（diff + rollback）
> - 修改决策速查表
> - Prompt 编辑 UI
> - ASIN 排名追踪
> - 主图变更检测
> - 跨项目知识库
> - ImageSlot 模型清理
>
> **Estimated Effort**: XL
> **Parallel Execution**: YES - 7 waves
> **Critical Path**: Schema fixes → Input UI → Brand Profile → A+ Content → QA Gate → Delivery → Feedback UI

---

## Context

### Original Request

老板要求「完美实现业务需求，实现业务目标」—— 将 `AI设计服务进化路线图.md` 中 L4 闭环阶段的所有需求落地到 auto-image-pipeline 系统中。共 17 项任务，P0→P3 全部实现，不妥协。

### Interview Summary

**Key Discussions**:

- **TDD 策略**：先写测试再实现，当前 211 tests 全绿
- **DB 迁移**：不用 Alembic，用 `create_all()` + 手动 `ALTER TABLE`
- **CSS 规范**：外部 style.css，禁止内联 `<style>`
- **前端**：纯 Jinja2 模板 + 原生 JS，不引入框架
- **P0→P3 全做**：无优先级妥协

**Research Findings**:

- APlusContent 模型缺 `layout` 字段，`module_type` 无枚举约束
- TagAssignment 模型缺 `tag_layer` 字段，无唯一约束
- 两个模型均「已建表但零集成」—— layers 无调用
- ImageSlot 仅在 2 个测试文件中被引用，可安全清理
- 当前 32 个 layer 函数，11 个 CLI 命令，10 个 Web 路由

### Metis Review

**Identified Gaps** (addressed):

- APlusContent schema 需扩展 → Task 0 schema 修复
- Brand Profile 限制最多 8 字段 → 遵循路线图 10 维度但存储为 JSON
- Prompt Editor 无 live preview → 明确排除
- Knowledge Base 仅 append-only → 明确约束
- 每个 task 原子提交 → Commit Strategy 已规划

---

## Work Objectives

### Core Objective

将 auto-image-pipeline 从 L3（流水线自动化）升级到 L4（闭环系统），实现客户触点、深度质检、高级数据结构、反馈驱动修改的完整闭环。

### Concrete Deliverables

- 6 个新 Web UI 页面（输入、上传、画像卡、反馈、Prompt 编辑、版本管理）
- 7 个新/扩展 layer 函数
- 4 个 schema 修改（APlusContent、TagAssignment、新增 ReferencePack、ConsistencyLock）
- QA Gate 从 1 硬门扩展到 5 硬门
- 交付包从 3 样扩展到 5 样

### Definition of Done

- [ ] `PYTHONPATH=. .venv/bin/pytest tests/ -q` → ALL PASS（目标 280+ tests）
- [ ] 所有 17 项路线图 L4 需求有对应实现代码
- [ ] Web UI 可正常访问和操作（Playwright 验证）
- [ ] QA Gate 5 硬门均可独立触发和通过/拒绝

### Must Have

- 引导式客户输入（5 组必问 + 5 组建议问）
- 品牌画像卡 10 维度
- A+ 内容 7 模块生成
- 三层标签体系（intent 6 + role 7）
- Reference Pack 6 组件
- 一致性系统 5 变量
- QA Gate 5 硬门
- 交付包 5 样东西
- 客户反馈 UI + 反馈→修改闭环

### Must NOT Have (Guardrails)

- ❌ 前端框架（React/Vue/Svelte 等）—— 纯 Jinja2 + 原生 JS
- ❌ Async/Celery/队列 —— 同步 Flask
- ❌ Alembic 迁移 —— `create_all()` + ALTER TABLE
- ❌ `as any` 类型标注
- ❌ `<style>` 内联 CSS —— 外部 style.css
- ❌ Prompt Editor live preview
- ❌ Knowledge Base 编辑/删除 —— 仅 append-only
- ❌ 新架构模式（微服务、事件驱动等）

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed. No exceptions.

### Test Decision

- **Infrastructure exists**: YES（pytest, 211 tests）
- **Automated tests**: TDD（RED→GREEN→REFACTOR）
- **Framework**: pytest（`PYTHONPATH=. .venv/bin/pytest tests/ -q`）

### QA Policy

Every task MUST include agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Web UI**: Use Playwright — Navigate, interact, assert DOM, screenshot
- **Layer/Logic**: Use Bash — pytest + direct function calls
- **CLI**: Use Bash — run `aip` commands, validate output
- **API**: Use Bash (curl) — POST/GET endpoints, assert response

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 0 (Foundation — schema fixes, no feature deps):
├── Task 0: Schema 修复（APlusContent + TagAssignment 扩展） [quick]

Wave 1 (P0 客户可感知 — 输入侧, MAX PARALLEL):
├── Task 1: 引导式客户输入 UI [visual-engineering]
├── Task 2: 素材上传 UI [visual-engineering]
├── Task 3: 品牌画像卡 UI [visual-engineering]

Wave 2 (P0 生成侧 + P1 标签/参考):
├── Task 4: A+ 内容生成逻辑 (depends: Task 0) [deep]
├── Task 5: 三层标签体系 (depends: Task 0) [deep]
├── Task 6: Reference Pack [deep]
├── Task 7: 一致性系统 [deep]

Wave 3 (P1 质量 + 交付):
├── Task 8: QA Gate 5 硬门完善 (depends: Task 7) [deep]
├── Task 9: 交付包完善 (depends: Task 4) [unspecified-high]

Wave 4 (P2 流程闭环 — UI 类, MAX PARALLEL):
├── Task 10: 客户反馈 UI [visual-engineering]
├── Task 11: 版本管理 [unspecified-high]
├── Task 12: 修改决策速查表 [unspecified-high]
├── Task 13: Prompt 编辑 UI [visual-engineering]

Wave 5 (P3 长期价值):
├── Task 14: ASIN 排名追踪 [unspecified-high]
├── Task 15: 主图变更检测 [unspecified-high]
├── Task 16: 跨项目知识库 [unspecified-high]

Wave 6 (清理):
├── Task 17: ImageSlot 模型清理 [quick]

Wave FINAL (验证):
├── F1: Plan Compliance Audit (oracle)
├── F2: Code Quality Review (unspecified-high)
├── F3: Real Manual QA (unspecified-high)
└── F4: Scope Fidelity Check (deep)
-> Present results -> Get explicit user okay

Critical Path: Task 0 → Task 4/5 → Task 8 → Task 9 → F1-F4 → user okay
Parallel Speedup: ~60% faster than sequential
Max Concurrent: 4 (Waves 1, 2, 4)
```

### Dependency Matrix

| Task | Depends On | Blocks |
| ---- | ---------- | ------ |
| 0    | —          | 4, 5   |
| 1    | —          | 10     |
| 2    | —          | —      |
| 3    | —          | —      |
| 4    | 0          | 9      |
| 5    | 0          | —      |
| 6    | —          | 8      |
| 7    | —          | 8      |
| 8    | 6, 7       | —      |
| 9    | 4          | —      |
| 10   | 1          | —      |
| 11   | —          | —      |
| 12   | —          | —      |
| 13   | —          | —      |
| 14   | —          | —      |
| 15   | —          | —      |
| 16   | —          | —      |
| 17   | —          | —      |

### Agent Dispatch Summary

- **Wave 0**: 1 task → `quick`
- **Wave 1**: 3 tasks → `visual-engineering` ×3
- **Wave 2**: 4 tasks → `deep` ×4
- **Wave 3**: 2 tasks → `deep` + `unspecified-high`
- **Wave 4**: 4 tasks → `visual-engineering` ×2 + `unspecified-high` ×2
- **Wave 5**: 3 tasks → `unspecified-high` ×3
- **Wave 6**: 1 task → `quick`
- **FINAL**: 4 tasks → `oracle` + `unspecified-high` ×2 + `deep`

---

## TODOs

- [x] 0. Schema 修复：APlusContent + TagAssignment 扩展

  **What to do**:
  - APlusContent 新增 `layout = Column(Text, nullable=True)`
  - APlusContent `module_type` 改 `String(30)` + `CheckConstraint` 枚举：HERO, BENEFIT, DETAIL, LIFESTYLE, COMPARISON, BRAND_STORY, CROSS_SELL
  - TagAssignment 新增 `tag_layer = Column(String(20), nullable=False)`（值：intent/role/scene）
  - TagAssignment 添加 `UniqueConstraint('entity_type', 'entity_id', 'tag_code')`
  - `__main__.py init` 添加 ALTER TABLE 兼容已有 DB
  - TDD：schema 约束测试

  **Must NOT do**: 不用 Alembic、不删现有数据

  **Recommended Agent Profile**: `quick`, Skills: []

  **Parallelization**: Wave 0 (solo) | Blocks: 4, 5 | Blocked By: None

  **References**:
  - `pipeline/models/aplus_content.py` — 当前 23 行，需扩展
  - `pipeline/models/tag_assignment.py` — 当前 12 行，需扩展
  - `pipeline/__main__.py` — init 命令 create_all() 位置
  - 路线图 — A+ 模块类型、三层标签定义

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_schema_l4.py -q` → PASS
  - [ ] module_type 只接受 7 种枚举值
  - [ ] 重复 tag 插入抛 IntegrityError

  **QA Scenarios**:

  ```
  Scenario: module_type 枚举约束
    Tool: Bash (pytest)
    Steps: 尝试 APlusContent(module_type="INVALID") → 断言异常
    Evidence: .sisyphus/evidence/task-0-module-type-constraint.txt

  Scenario: tag 唯一约束
    Tool: Bash (pytest)
    Steps: 插入重复 (entity_type, entity_id, tag_code) → 断言 IntegrityError
    Evidence: .sisyphus/evidence/task-0-tag-unique.txt
  ```

  **Commit**: `fix(models): extend APlusContent and TagAssignment schemas for L4`

- [x] 1. 引导式客户输入 UI

  **What to do**:
  - 新建 `pipeline/web/templates/customer_input.html` — 分步表单 Step 1-5 必问 + 6-10 建议问
  - 5 组必问：产品基本信息、目标受众、竞品分析、视觉偏好、预算与时间
  - 5 组建议问：品牌故事、USP、痛点场景、生活方式、季节/节日
  - 新增路由 `GET/POST /input/new` 和 `GET/POST /input/<project_id>/edit`
  - 表单数据存入 Project `customer_brief` JSON 字段
  - 进度指示器，CSS 写入 style.css
  - TDD：路由测试

  **Must NOT do**: 不引入前端框架、不用内联 `<style>`

  **Recommended Agent Profile**: `visual-engineering`, Skills: [`frontend-ui-ux`]

  **Parallelization**: Wave 1 (with 2, 3) | Blocks: 10 | Blocked By: None

  **References**:
  - `pipeline/web/app.py` — 路由模式
  - `pipeline/web/templates/index.html` — 模板结构
  - `pipeline/web/static/style.css` — CSS 规范
  - `pipeline/models/project.py` — Project 模型
  - 路线图 — 「客户提资清单」完整列表

  **Acceptance Criteria**:
  - [ ] GET `/input/new` → 200，含 5 必问步骤
  - [ ] POST valid data → 302 redirect
  - [ ] POST missing required → 400
  - [ ] pytest tests/test_customer_input.py → PASS

  **QA Scenarios**:

  ```
  Scenario: 填写必问项并提交
    Tool: Playwright
    Steps: Navigate /input/new → 填 5 必问 → 提交 → 断言跳转到 /project/<id>
    Evidence: .sisyphus/evidence/task-1-submit-success.png

  Scenario: 必填为空提交被拒
    Tool: Playwright
    Steps: Navigate /input/new → 不填 → 提交 → 断言显示错误
    Evidence: .sisyphus/evidence/task-1-validation-error.png
  ```

  **Commit**: `feat(web): add guided customer input UI with 10 question groups`

- [x] 2. 素材上传 UI

  **What to do**:
  - 新建 `pipeline/web/templates/upload.html` — 拖拽上传 + 预览
  - 支持 jpg/png/webp/svg，最大 10MB
  - 存储到 `output/<project_id>/assets/`
  - 缩略图预览 + 删除按钮
  - 新增路由 `GET/POST /upload/<project_id>`
  - TDD：路由测试（上传成功、类型拒绝、大小限制）

  **Must NOT do**: 不引入前端框架、不用内联 `<style>`、不做异步上传

  **Recommended Agent Profile**: `visual-engineering`, Skills: [`frontend-ui-ux`]

  **Parallelization**: Wave 1 (with 1, 3) | Blocks: None | Blocked By: None

  **References**:
  - `pipeline/web/app.py` — 路由模式
  - `pipeline/config.py` — OUTPUT_DIR 路径

  **Acceptance Criteria**:
  - [ ] POST jpg → 文件出现在 output/1/assets/
  - [ ] POST .exe → 400 拒绝
  - [ ] pytest tests/test_upload.py → PASS

  **QA Scenarios**:

  ```
  Scenario: 上传 jpg 成功
    Tool: Playwright
    Steps: Navigate /upload/1 → 选择 test.jpg → 上传 → 断言缩略图出现
    Evidence: .sisyphus/evidence/task-2-upload-success.png

  Scenario: 拒绝非图片
    Tool: Bash (curl)
    Steps: curl -X POST -F "file=@test.txt" /upload/1 → 断言 400
    Evidence: .sisyphus/evidence/task-2-reject-filetype.txt
  ```

  **Commit**: `feat(web): add asset upload UI with drag-and-drop`

- [x] 3. 品牌画像卡 UI

  **What to do**:
  - 新建 `pipeline/web/templates/brand_profile.html` — 10 维度卡片展示 + 编辑
  - 10 维度：品牌调性、色彩体系、字体偏好、摄影风格、模特类型、场景偏好、构图偏好、材质质感、竞品定位、品牌故事
  - 新增 `pipeline/models/brand_profile.py` — BrandProfile 模型
  - 新增 `pipeline/layers/brand_profiler.py` — `build_brand_profile(project_id)`
  - 路由 `GET/POST /brand-profile/<project_id>`
  - TDD：模型 + layer + 路由测试

  **Must NOT do**: 不超过 10 维度、不用内联 `<style>`

  **Recommended Agent Profile**: `visual-engineering`, Skills: [`frontend-ui-ux`]

  **Parallelization**: Wave 1 (with 1, 2) | Blocks: None | Blocked By: None

  **References**:
  - `pipeline/models/project.py` — Project 模型
  - `pipeline/layers/brief_generator.py` — brief 生成逻辑参考
  - 路线图 — 「品牌画像卡」10 维度定义

  **Acceptance Criteria**:
  - [ ] GET `/brand-profile/1` → 200，含 10 维度卡片
  - [ ] POST 编辑 → 更新成功
  - [ ] pytest tests/test_brand_profile.py → PASS

  **QA Scenarios**:

  ```
  Scenario: 查看 10 维度
    Tool: Playwright
    Steps: Navigate /brand-profile/1 → 断言 10 个卡片标题均可见
    Evidence: .sisyphus/evidence/task-3-view-profile.png

  Scenario: 编辑品牌调性
    Tool: Playwright
    Steps: 点击编辑 → 输入 "简约现代" → 保存 → 刷新 → 断言持久化
    Evidence: .sisyphus/evidence/task-3-edit-profile.png
  ```

  **Commit**: `feat(web): add brand profile card UI with 10 dimensions`

- [x] 4. A+ 内容生成逻辑

  **What to do**:
  - 新建 `pipeline/layers/aplus_generator.py`，包含 `generate_aplus_storyboard(project_id)` 函数
  - 路线图定义7模块：Brand Story / Product Highlight / Lifestyle Scene / Comparison Chart / Technical Specs / Social Proof / CTA
  - 调用 LLM（同 brief_generator 模式）生成各模块的 headline + body
  - 将结果写入 `APlusContent` 模型（已有 module_type/headline/body/image_refs/sort_order）
  - 在 `orchestrator.py` 的流程中，在 `step_generate()` 之后加入 `step_aplus()` 步骤
  - CLI: 在 `__main__.py` 新增 `aplus` 子命令
  - Web: 新增 `/project/<id>/aplus` GET 路由展示 A+ storyboard
  - 新建 `templates/aplus.html` 模板，按 sort_order 渲染7模块卡片
  - **TDD**: 先写测试 `tests/test_aplus_generator.py`（mock LLM，断言7条 APlusContent 记录写入DB）

  **Must NOT do**:
  - 不引入新 LLM provider（复用现有 Gemini 调用模式）
  - 不修改 APlusContent 模型字段（Task 0 已修复 schema）
  - 不添加 `<style>` 内联 CSS

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 需要理解 orchestrator 流水线模式并安全插入新步骤，涉及 LLM 集成
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 5, 6, 7)
  - **Blocks**: F1-F4
  - **Blocked By**: Task 0 (schema fixes)

  **References**:
  - `pipeline/layers/brief_generator.py` — LLM 调用模式（Gemini API + JSON解析）
  - `pipeline/orchestrator.py:step_generate()` — 插入 step_aplus 的位置
  - `pipeline/models/aplus_content.py` — APlusContent 模型字段
  - `pipeline/__main__.py` — CLI 命令注册模式
  - `pipeline/web/app.py` — Flask 路由注册模式
  - `tests/test_brief_generator.py` — LLM layer 测试模式（mock）
  - 路线图：「A+ Content Storyboard」章节（7模块定义）

  **Acceptance Criteria**:
  - [ ] `tests/test_aplus_generator.py` 存在且 PASS
  - [ ] `generate_aplus_storyboard(project_id)` 生成7条 APlusContent 记录
  - [ ] `aip aplus --project-id 1` CLI 命令可用
  - [ ] GET `/project/1/aplus` 返回200

  **QA Scenarios**:

  ```
  Scenario: CLI 生成 A+ storyboard
    Tool: Bash
    Steps:
      1. PYTHONPATH=. python -m pipeline.__main__ aplus --project-id 1
      2. 检查 DB: SELECT count(*) FROM aplus_content WHERE project_id=1 → 7
      3. SELECT DISTINCT module_type FROM aplus_content WHERE project_id=1 → 7种类型
    Expected Result: 7条记录，覆盖全部模块类型
    Evidence: .sisyphus/evidence/task-4-cli-aplus.txt

  Scenario: Web 页面展示 A+ storyboard
    Tool: Playwright
    Steps: Navigate /project/1/aplus → 断言页面含7个模块卡片 → 每个卡片有 headline 和 body
    Expected Result: 7个模块按 sort_order 排列
    Evidence: .sisyphus/evidence/task-4-web-aplus.png

  Scenario: 无数据时优雅降级
    Tool: Playwright
    Steps: Navigate /project/999/aplus → 断言显示空状态提示
    Expected Result: 不报500，显示提示信息
    Evidence: .sisyphus/evidence/task-4-aplus-empty.png
  ```

  **Commit**: `feat(layers): implement A+ content generation logic`

- [x] 5. 三层标签体系

  **What to do**:
  - 新建 `pipeline/layers/tag_system.py`，定义标签常量和打标逻辑
  - 路线图三层标签：
    - Intent 层 (INT_01~06): HERO / LIFESTYLE / INFOGRAPHIC / COMPARISON / SOCIAL_PROOF / DETAIL
    - Role 层 (ROLE_01~07): ATTENTION / DESIRE / TRUST / INFORM / DIFFERENTIATE / CONVERT / RETAIN
    - Scene 层: 由 LLM 根据产品类目动态生成
  - `assign_tags(project_id, slot_plan_id)` — 为 SlotPlan 的每个 slot 自动分配 Intent + Role 标签
  - `get_scene_tags(project_id)` — 调用 LLM 生成场景标签
  - 将标签写入 `TagAssignment` 模型（Task 0 已扩展 tag_layer 字段）
  - 修改 `slot_planner.py` 的 `create_slot_plan()` 在创建 slot 后调用 `assign_tags()`
  - **TDD**: `tests/test_tag_system.py`（mock LLM，断言标签分配逻辑）

  **Must NOT do**:
  - 不修改 TagAssignment 模型字段（Task 0 已修复）
  - 不硬编码 Scene 标签（由 LLM 生成）

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 需要理解标签体系设计和 slot_planner 集成点
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 4, 6, 7)
  - **Blocks**: Task 8 (QA Gate 需要标签校验)
  - **Blocked By**: Task 0 (schema fixes)

  **References**:
  - `pipeline/layers/slot_planner.py:create_slot_plan()` — 集成点
  - `pipeline/models/tag_assignment.py` — TagAssignment 模型
  - `pipeline/models/slot_plan.py` — SlotPlan 模型（slot 定义）
  - 路线图：「三层标签体系」章节（INT_01~06 / ROLE_01~07 完整定义）

  **Acceptance Criteria**:
  - [ ] `tests/test_tag_system.py` 存在且 PASS
  - [ ] `assign_tags()` 为每个 slot 分配至少 1 个 Intent + 1 个 Role 标签
  - [ ] TagAssignment 记录含 tag_layer 字段（intent/role/scene）

  **QA Scenarios**:

  ```
  Scenario: 标签分配后查询
    Tool: Bash
    Steps:
      1. PYTHONPATH=. python -c "from pipeline.layers.tag_system import assign_tags; assign_tags(1, 1)"
      2. SELECT count(*) FROM tag_assignment WHERE project_id=1 → ≥14 (7 slots × 2 layers)
      3. SELECT DISTINCT tag_layer FROM tag_assignment → intent, role
    Expected Result: 每个 slot 至少2条标签记录
    Evidence: .sisyphus/evidence/task-5-tag-assign.txt

  Scenario: 无效 project_id
    Tool: Bash
    Steps: assign_tags(999, 1) → 断言抛出或返回空列表
    Expected Result: 不崩溃，优雅处理
    Evidence: .sisyphus/evidence/task-5-tag-invalid.txt
  ```

  **Commit**: `feat(layers): implement 3-layer tag system`

- [x] 6. Reference Pack 数据结构 + 填充

  **What to do**:
  - 新建 `pipeline/models/reference_pack.py` — ReferencePack ORM 模型
  - 路线图6组件：product_truth / brand_rules / winning_examples / competitor_baseline / negative_cases / angle_matrix
  - 每个组件存储为 JSON 字段（内容由现有分析层自动填充）
  - 新建 `pipeline/layers/reference_pack.py`:
    - `build_reference_pack(project_id)` — 从现有数据（CompetitorListing, ReviewCluster, BrandProfile, AmazonBenchmark）聚合生成6组件
    - `get_reference_pack(project_id)` — 查询
  - 修改 `prompt_engine.py` 的 `assemble_prompt()` 在组装时注入 reference_pack 上下文
  - **TDD**: `tests/test_reference_pack.py`

  **Must NOT do**:
  - 不新增外部 API 调用（纯聚合现有数据）
  - product_truth 从 Project 模型提取，不重复存储原始数据

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 需要理解多个现有模型的数据关系并设计聚合逻辑
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 4, 5, 7)
  - **Blocks**: Task 8 (QA Gate Reference Chain 校验)
  - **Blocked By**: Task 0 (schema fixes)

  **References**:
  - `pipeline/models/competitor_listing.py` — CompetitorListing 字段（competitor_baseline 数据源）
  - `pipeline/models/review_cluster.py` — ReviewCluster 字段（winning_examples 数据源）
  - `pipeline/models/brand_profile.py` — BrandProfile 字段（brand_rules 数据源）
  - `pipeline/models/amazon_benchmark.py` — AmazonBenchmark 字段（competitor_baseline 数据源）
  - `pipeline/layers/prompt_engine.py:assemble_prompt()` — Prompt 组装集成点
  - 路线图：「reference_pack」章节（6组件定义）

  **Acceptance Criteria**:
  - [ ] `tests/test_reference_pack.py` 存在且 PASS
  - [ ] `build_reference_pack(1)` 生成1条 ReferencePack 记录，含6个非空 JSON 字段
  - [ ] `assemble_prompt()` 输出包含 reference_pack 上下文

  **QA Scenarios**:

  ```
  Scenario: 构建 reference pack
    Tool: Bash
    Steps:
      1. PYTHONPATH=. python -c "from pipeline.layers.reference_pack import build_reference_pack; rp = build_reference_pack(1); print(rp.product_truth)"
      2. SELECT count(*) FROM reference_pack WHERE project_id=1 → 1
    Expected Result: 6个字段均非空 JSON
    Evidence: .sisyphus/evidence/task-6-build-rp.txt

  Scenario: Prompt 注入 reference_pack
    Tool: Bash
    Steps: assemble_prompt(1) → 输出字符串包含 "reference" 相关内容
    Expected Result: prompt 文本含 reference_pack 数据
    Evidence: .sisyphus/evidence/task-6-prompt-rp.txt
  ```

  **Commit**: `feat(layers): implement reference pack 6 components`

- [x] 7. 一致性系统5变量

  **What to do**:
  - 新建 `pipeline/models/consistency_profile.py` — ConsistencyProfile ORM 模型
  - 路线图5变量：lighting_style / color_palette / camera_angle / element_density / text_overlay_style
  - 每个变量为字符串字段，记录锁定值
  - 新建 `pipeline/layers/consistency_system.py`:
    - `create_consistency_profile(project_id, **kwargs)` — 创建/更新一致性配置
    - `get_consistency_profile(project_id)` — 查询
    - `validate_consistency(project_id, image_path)` — 调用 VisionAnalyzer 校验图片是否符合一致性配置
  - 修改 `prompt_engine.py` 的 `assemble_prompt()` 注入一致性约束
  - Web: 新增 `/project/<id>/consistency` GET/POST 路由（查看/设置一致性变量）
  - **TDD**: `tests/test_consistency_system.py`

  **Must NOT do**:
  - validate_consistency 使用现有 VisionAnalyzer（不新增 vision API）
  - 不引入 `<style>` 内联 CSS

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 需要 vision_analyzer 集成和 prompt_engine 修改
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 4, 5, 6)
  - **Blocks**: Task 8 (QA Gate 一致性校验)
  - **Blocked By**: Task 0 (schema fixes)

  **References**:
  - `pipeline/layers/vision_analyzer.py` — VisionAnalyzer 调用模式（validate_consistency 复用）
  - `pipeline/layers/prompt_engine.py:assemble_prompt()` — 一致性约束注入点
  - `pipeline/web/app.py` — Flask 路由模式
  - 路线图：「一致性系统」章节（5变量定义）

  **Acceptance Criteria**:
  - [ ] `tests/test_consistency_system.py` 存在且 PASS
  - [ ] `create_consistency_profile(1, lighting_style="studio soft")` 成功写入 DB
  - [ ] `assemble_prompt()` 输出包含一致性约束
  - [ ] GET `/project/1/consistency` 返回200

  **QA Scenarios**:

  ```
  Scenario: 创建一致性配置
    Tool: Bash
    Steps:
      1. PYTHONPATH=. python -c "from pipeline.layers.consistency_system import create_consistency_profile; create_consistency_profile(1, lighting_style='studio soft', color_palette='warm neutral')"
      2. SELECT lighting_style FROM consistency_profile WHERE project_id=1 → 'studio soft'
    Expected Result: 5变量均可设置和查询
    Evidence: .sisyphus/evidence/task-7-create-consistency.txt

  Scenario: Web 查看一致性配置
    Tool: Playwright
    Steps: Navigate /project/1/consistency → 断言页面含5个变量字段
    Expected Result: 显示 lighting/color/camera/density/text 五项
    Evidence: .sisyphus/evidence/task-7-web-consistency.png
  ```

  **Commit**: `feat(layers): implement consistency lock system`

- [ ] 8. QA Gate 5硬门完善

  **What to do**:
  - 路线图要求5硬门串联：①合规前置检查 ②Visual Anchor匹配 ③Reference Chain验证 ④一致性校验 ⑤综合QA Gate
  - 当前 `qa_gate.py` 仅有综合 QA Gate（第⑤门），需新增前4门
  - 在 `pipeline/layers/qa_gate.py` 新增4个函数：
    - `check_compliance(project_id, image_path)` — 检查图片尺寸/格式/文件大小是否符合 Amazon 规范（JPEG/PNG, ≥1000px, ≤10MB）
    - `check_visual_anchor(project_id, image_path)` — 调用 VisionAnalyzer 检查主视觉锚点是否与 slot_plan 的 visual_focus 匹配
    - `check_reference_chain(project_id, image_path)` — 验证生成图是否有对应 reference_pack 条目（通过 DB 查询）
    - `check_consistency(project_id, image_path)` — 调用 consistency_system.validate_consistency()
  - 修改现有 `run_qa_gate()` 函数：串联调用5个 check，任一 FAIL 则整体 FAIL，返回结构化报告 `{"gate_1": {status, details}, ...}`
  - **TDD**: `tests/test_qa_gate_5doors.py` — 每门至少2个测试（pass/fail）

  **Must NOT do**:
  - 不删除现有 `run_qa_gate()` 逻辑，而是包装为第5门
  - 不引入新的 vision API 调用（复用 VisionAnalyzer）

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 需要集成多个 layer（vision_analyzer, consistency_system, reference_pack）并串联逻辑
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (with Task 9)
  - **Blocks**: Task F1-F4
  - **Blocked By**: Tasks 6 (reference_pack), 7 (consistency_system)

  **References**:
  - `pipeline/layers/qa_gate.py` — 现有 run_qa_gate() 作为第5门包装
  - `pipeline/layers/vision_analyzer.py` — VisionAnalyzer 调用模式（门②④复用）
  - `pipeline/layers/consistency_system.py` — validate_consistency()（门④调用）
  - `pipeline/models/reference_pack.py` — reference_pack 查询（门③验证）
  - 路线图：「QA Gate」章节（5硬门定义）

  **Acceptance Criteria**:
  - [ ] `tests/test_qa_gate_5doors.py` 存在且 PASS（≥10 tests）
  - [ ] `run_qa_gate()` 返回包含 gate_1 ~ gate_5 的字典
  - [ ] 合规检查：非JPEG/PNG → gate_1 FAIL
  - [ ] 无 reference_pack → gate_3 FAIL

  **QA Scenarios**:

  ```
  Scenario: 合规前置检查 — 文件太小
    Tool: Bash
    Steps:
      1. 创建一个 100x100 的测试图片
      2. PYTHONPATH=. python -c "from pipeline.layers.qa_gate import check_compliance; r = check_compliance(1, 'test_small.jpg'); print(r)"
    Expected Result: status='FAIL', details 包含 'minimum 1000px'
    Evidence: .sisyphus/evidence/task-8-compliance-fail.txt

  Scenario: 5门串联 — 全通过
    Tool: Bash
    Steps:
      1. 准备符合条件的项目（有 reference_pack, consistency_profile, 合规图片）
      2. PYTHONPATH=. python -c "from pipeline.layers.qa_gate import run_qa_gate; r = run_qa_gate(1, 'test_ok.jpg'); print(r)"
    Expected Result: 5个 gate 全部 status='PASS'
    Evidence: .sisyphus/evidence/task-8-all-pass.txt
  ```

  **Commit**: `feat(qa): implement all 5 QA gate hard checks`

- [ ] 9. 交付包5样东西完善

  **What to do**:
  - 路线图要求交付包含5样东西：①图片文件 ②preview_list.html ③delivery_notes.md ④version_log.json ⑤spec_check.json
  - 当前 `delivery.py` 仅生成图片文件和基础报告
  - 修改 `pipeline/layers/delivery.py`:
    - `generate_preview_html(project_id)` — 生成所有图片的可视化预览 HTML（含 slot 名称、尺寸、用途说明）
    - `generate_delivery_notes(project_id)` — 生成 Markdown 交付说明（项目信息、设计决策摘要、使用建议）
    - `generate_version_log(project_id)` — 从 DB 聚合版本历史输出 JSON
    - `generate_spec_check(project_id)` — 输出各图片的规格检查结果 JSON（尺寸、格式、DPI、文件大小）
    - 修改 `create_delivery_package()` — 调用以上4个函数，打包5样东西到 `output/{project_id}/delivery/`
  - **TDD**: `tests/test_delivery_package.py`

  **Must NOT do**:
  - preview_list.html 使用外部 CSS 引用（`style.css`），不内联 `<style>`
  - 不引入 ZIP 打包（保持目录结构）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 文件生成逻辑，不需要深度架构但需要多种输出格式
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Task 8)
  - **Blocks**: Task F1-F4
  - **Blocked By**: Task 0 (schema)

  **References**:
  - `pipeline/layers/delivery.py` — 现有 create_delivery_package() 扩展
  - `pipeline/web/static/style.css` — preview_list.html 引用样式
  - 路线图：「交付包」章节（5样东西定义）

  **Acceptance Criteria**:
  - [ ] `tests/test_delivery_package.py` 存在且 PASS
  - [ ] `output/1/delivery/` 下生成5种文件
  - [ ] `preview_list.html` 不含 `<style>` 标签
  - [ ] `spec_check.json` 包含每张图的 width/height/format/filesize

  **QA Scenarios**:

  ```
  Scenario: 生成完整交付包
    Tool: Bash
    Steps:
      1. PYTHONPATH=. python -c "from pipeline.layers.delivery import create_delivery_package; create_delivery_package(1)"
      2. ls output/1/delivery/
    Expected Result: 目录含 preview_list.html, delivery_notes.md, version_log.json, spec_check.json
    Evidence: .sisyphus/evidence/task-9-delivery-ls.txt

  Scenario: preview_list.html 无内联CSS
    Tool: Bash
    Steps: grep '<style>' output/1/delivery/preview_list.html
    Expected Result: 无匹配（exit code 1）
    Evidence: .sisyphus/evidence/task-9-no-inline-css.txt
  ```

  **Commit**: `feat(delivery): complete delivery package 5 items`

- [x] 10. 客户反馈UI

  **What to do**:
  - 新建 `pipeline/models/client_feedback.py` — ClientFeedback ORM 模型
    - 字段：id, project_id(FK), slot_name, feedback_type(ENUM: approve/revise/reject), feedback_text, created_at
  - 新建 `pipeline/layers/feedback_handler.py`:
    - `submit_feedback(project_id, slot_name, feedback_type, text)` — 保存反馈到 DB
    - `get_feedback_summary(project_id)` — 汇总各 slot 的反馈状态
    - `apply_feedback(project_id)` — 根据反馈类型触发对应动作（approve→标记完成, revise→重新生成, reject→标记废弃）
  - Web 路由:
    - GET `/project/<id>/feedback` — 展示所有 slot 图片 + 反馈表单
    - POST `/project/<id>/feedback` — 提交反馈
  - 模板: `templates/feedback.html` — 每个 slot 显示图片缩略图 + approve/revise/reject 按钮 + 文本框
  - **TDD**: `tests/test_feedback_handler.py`

  **Must NOT do**:
  - 不引入 JavaScript 框架（纯 HTML form）
  - 不内联 `<style>` CSS

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Web UI + 模型 + layer 逻辑，中等复杂度
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 11, 12, 13)
  - **Blocks**: Task F1-F4
  - **Blocked By**: Task 0 (schema)

  **References**:
  - `pipeline/models/project.py` — FK 关联模式
  - `pipeline/web/app.py` — Flask 路由模式（GET/POST pattern）
  - `pipeline/web/templates/` — 现有模板结构
  - `pipeline/layers/feedback_loop.py` — 现有反馈逻辑（不重复，新模块处理客户端反馈）
  - 路线图：「客户反馈」章节

  **Acceptance Criteria**:
  - [ ] `tests/test_feedback_handler.py` 存在且 PASS
  - [ ] `submit_feedback(1, 'main', 'revise', 'too dark')` 写入 DB
  - [ ] GET `/project/1/feedback` 返回200
  - [ ] POST 提交后 redirect 回 feedback 页面

  **QA Scenarios**:

  ```
  Scenario: 提交反馈并查看
    Tool: Playwright
    Steps:
      1. Navigate to /project/1/feedback
      2. 选择 slot "main" 的 "revise" radio
      3. 在文本框输入 "背景太暗，需要提亮"
      4. 点击提交按钮
      5. 断言页面刷新后显示 "revise" 状态
    Expected Result: 反馈已保存且页面显示更新状态
    Evidence: .sisyphus/evidence/task-10-feedback-submit.png

  Scenario: 反馈汇总
    Tool: Bash
    Steps: PYTHONPATH=. python -c "from pipeline.layers.feedback_handler import get_feedback_summary; print(get_feedback_summary(1))"
    Expected Result: 返回字典含各 slot 的 feedback_type
    Evidence: .sisyphus/evidence/task-10-summary.txt
  ```

  **Commit**: `feat(web): add customer feedback UI`

- [x] 11. 版本管理

  **What to do**:
  - 新建 `pipeline/models/delivery_version.py` — DeliveryVersion ORM 模型
    - 字段：id, project_id(FK), version_number(int), created_at, trigger(ENUM: initial/revision/feedback), change_summary(text), file_manifest(JSON, 文件名列表)
  - 新建 `pipeline/layers/version_manager.py`:
    - `create_version(project_id, trigger, change_summary)` — 快照当前 delivery 目录，版本号自增
    - `get_version_history(project_id)` — 查询所有版本
    - `get_version_diff(project_id, v1, v2)` — 对比两个版本的 file_manifest 差异
    - `rollback_version(project_id, target_version)` — 恢复到指定版本的文件
  - 修改 `delivery.py` — `create_delivery_package()` 完成后自动调用 `create_version()`
  - 修改 `feedback_handler.py` — `apply_feedback()` 的 revise 动作完成后调用 `create_version(trigger='revision')`
  - Web: GET `/project/<id>/versions` — 版本历史列表（版本号、时间、触发类型、变更摘要）
  - **TDD**: `tests/test_version_manager.py`

  **Must NOT do**:
  - 不用 git 做版本管理（用文件复制 + DB 记录）
  - 版本文件存储在 `output/{project_id}/versions/v{N}/`

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 跨多个 layer 集成（delivery + feedback_handler），需要文件系统操作
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 10, 12, 13)
  - **Blocks**: Task F1-F4
  - **Blocked By**: Task 9 (delivery package), Task 10 (feedback handler)

  **References**:
  - `pipeline/layers/delivery.py` — create_delivery_package() 集成点
  - `pipeline/layers/feedback_handler.py` — apply_feedback() 集成点
  - `pipeline/web/app.py` — Flask 路由模式
  - 路线图：「版本管理」章节

  **Acceptance Criteria**:
  - [ ] `tests/test_version_manager.py` 存在且 PASS
  - [ ] `create_version(1, 'initial', 'first delivery')` 创建 v1 目录
  - [ ] `get_version_diff(1, 1, 2)` 返回文件差异列表
  - [ ] GET `/project/1/versions` 返回200

  **QA Scenarios**:

  ```
  Scenario: 自动创建版本
    Tool: Bash
    Steps:
      1. PYTHONPATH=. python -c "from pipeline.layers.delivery import create_delivery_package; create_delivery_package(1)"
      2. ls output/1/versions/
    Expected Result: 存在 v1/ 目录
    Evidence: .sisyphus/evidence/task-11-auto-version.txt

  Scenario: 版本差异对比
    Tool: Bash
    Steps:
      1. 创建两个版本（第二次修改一个文件）
      2. PYTHONPATH=. python -c "from pipeline.layers.version_manager import get_version_diff; print(get_version_diff(1, 1, 2))"
    Expected Result: 返回 added/removed/modified 文件列表
    Evidence: .sisyphus/evidence/task-11-diff.txt
  ```

  **Commit**: `feat(layers): add version management with diff and rollback`

- [x] 12. 修改决策速查表

  **What to do**:
  - 新建 `pipeline/layers/revision_lookup.py`:
    - 定义 `REVISION_TABLE` 字典常量 — 键为客户反馈关键词（如 "太暗"/"颜色不对"/"构图问题"/"文字不清"/"风格不符"），值为对应的 prompt 修改建议和重新生成策略
    - `lookup_revision_action(feedback_text)` — 解析反馈文本，匹配关键词，返回修改建议
    - `auto_apply_revision(project_id, slot_name, feedback_text)` — 查表 → 修改 prompt 参数 → 调用 prompt_engine 重新生成
  - 修改 `feedback_handler.py` — `apply_feedback()` 的 revise 分支调用 `auto_apply_revision()`
  - Web: GET `/revision-guide` — 展示速查表（所有关键词→动作映射）
  - **TDD**: `tests/test_revision_lookup.py`

  **Must NOT do**:
  - 速查表用 Python 字典硬编码，不引入额外配置文件格式
  - 不引入 NLP/AI 做关键词匹配（简单字符串 in 匹配）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 本质是字典查表 + 字符串匹配，逻辑简单
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 10, 11, 13)
  - **Blocks**: Task F1-F4
  - **Blocked By**: Task 10 (feedback_handler)

  **References**:
  - `pipeline/layers/feedback_handler.py` — apply_feedback() 集成点
  - `pipeline/layers/prompt_engine.py` — 重新生成 prompt 的入口
  - 路线图：「修改决策速查表」章节

  **Acceptance Criteria**:
  - [ ] `tests/test_revision_lookup.py` 存在且 PASS
  - [ ] `lookup_revision_action("背景太暗")` 返回含 prompt 修改建议的字典
  - [ ] 未匹配关键词返回 default fallback 建议
  - [ ] GET `/revision-guide` 返回200

  **QA Scenarios**:

  ```
  Scenario: 关键词匹配
    Tool: Bash
    Steps: PYTHONPATH=. python -c "from pipeline.layers.revision_lookup import lookup_revision_action; print(lookup_revision_action('背景太暗了'))"
    Expected Result: 返回 {"action": "adjust_lighting", "prompt_modifier": "increase brightness..."}
    Evidence: .sisyphus/evidence/task-12-lookup.txt

  Scenario: 未匹配时 fallback
    Tool: Bash
    Steps: PYTHONPATH=. python -c "from pipeline.layers.revision_lookup import lookup_revision_action; print(lookup_revision_action('随便改改'))"
    Expected Result: 返回 default fallback 建议（非 None）
    Evidence: .sisyphus/evidence/task-12-fallback.txt
  ```

  **Commit**: `feat(layers): add revision decision lookup table`

- [ ] 13. Prompt 编辑 UI

  **What to do**:
  - Web 路由:
    - GET `/project/<id>/prompts` — 展示当前项目所有 slot 的 prompt（从 prompt_manager 获取）
    - GET `/project/<id>/prompt/<slot>` — 单个 prompt 编辑页面（textarea 显示完整 prompt 文本）
    - POST `/project/<id>/prompt/<slot>` — 保存修改后的 prompt
  - 模板: `templates/prompt_editor.html` — prompt 文本 textarea + 保存按钮 + 变量高亮提示
  - 模板: `templates/prompt_list.html` — 所有 slot 的 prompt 列表 + 编辑链接
  - 修改 `prompt_manager.py` — 新增 `update_prompt_text(project_id, slot_name, new_text)` 函数
  - **TDD**: `tests/test_prompt_editor.py`

  **Must NOT do**:
  - 不引入 JavaScript 富文本编辑器（纯 textarea）
  - 不内联 `<style>` CSS

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Web UI + 模板 + layer 逻辑
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 10, 11, 12)
  - **Blocks**: Task F1-F4
  - **Blocked By**: Task 0 (schema)

  **References**:
  - `pipeline/layers/prompt_manager.py` — 现有 prompt CRUD 函数
  - `pipeline/web/app.py` — Flask 路由模式
  - `pipeline/web/templates/` — 现有模板结构
  - 路线图：「Prompt资产管理」章节

  **Acceptance Criteria**:
  - [ ] `tests/test_prompt_editor.py` 存在且 PASS
  - [ ] GET `/project/1/prompts` 返回200，显示 slot 列表
  - [ ] POST `/project/1/prompt/main` 成功更新 prompt 文本
  - [ ] 修改后 GET 页面显示更新后的文本

  **QA Scenarios**:

  ```
  Scenario: 查看并编辑 prompt
    Tool: Playwright
    Steps:
      1. Navigate to /project/1/prompts
      2. 点击 "main" slot 的编辑链接
      3. 在 textarea 中追加 " --style cinematic"
      4. 点击保存按钮
      5. 断言页面显示更新后的 prompt 文本含 "--style cinematic"
    Expected Result: prompt 修改成功并显示
    Evidence: .sisyphus/evidence/task-13-prompt-edit.png

  Scenario: prompt 列表展示
    Tool: Bash
    Steps: curl -s http://localhost:5000/project/1/prompts | grep 'main'
    Expected Result: HTML 含 "main" slot 条目
    Evidence: .sisyphus/evidence/task-13-prompt-list.txt
  ```

  **Commit**: `feat(web): add prompt editor UI`

- [ ] 14. ASIN 排名追踪

  **What to do**:
  - 新建 `pipeline/models/asin_ranking.py` — ASINRanking ORM 模型
    - 字段：id, project_id(FK), asin, keyword, rank_position(int), tracked_at(datetime), category_name
  - 新建 `pipeline/layers/ranking_tracker.py`:
    - `record_ranking(project_id, asin, keyword, position, category)` — 记录排名快照
    - `get_ranking_history(project_id, asin, keyword, days=30)` — 查询排名历史趋势
    - `get_ranking_summary(project_id)` — 汇总各 ASIN 的最新排名
  - Web: GET `/project/<id>/rankings` — 排名历史展示（表格：ASIN / keyword / 最新排名 / 趋势）
  - **TDD**: `tests/test_ranking_tracker.py`

  **Must NOT do**:
  - 不实现自动爬取 Amazon 排名（仅提供手动记录/导入接口）
  - 不引入图表库（纯 HTML 表格）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单 CRUD 模型 + 查询
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with Tasks 15, 16)
  - **Blocks**: Task F1-F4
  - **Blocked By**: Task 0 (schema)

  **References**:
  - `pipeline/models/project.py` — FK 关联模式
  - `pipeline/web/app.py` — Flask 路由模式
  - 路线图：「ASIN排名追踪」章节

  **Acceptance Criteria**:
  - [ ] `tests/test_ranking_tracker.py` 存在且 PASS
  - [ ] `record_ranking(1, 'B0XXX', 'dog bowl', 15, 'Pet Supplies')` 写入 DB
  - [ ] `get_ranking_history()` 返回时间序列数据
  - [ ] GET `/project/1/rankings` 返回200

  **QA Scenarios**:

  ```
  Scenario: 记录并查询排名
    Tool: Bash
    Steps:
      1. PYTHONPATH=. python -c "from pipeline.layers.ranking_tracker import record_ranking, get_ranking_summary; record_ranking(1, 'B0XXX', 'dog bowl', 15, 'Pet'); record_ranking(1, 'B0XXX', 'dog bowl', 12, 'Pet'); print(get_ranking_summary(1))"
    Expected Result: 返回含最新排名12的摘要
    Evidence: .sisyphus/evidence/task-14-ranking.txt
  ```

  **Commit**: `feat(layers): add ASIN ranking tracker`

- [ ] 15. 主图变更检测

  **What to do**:
  - 新建 `pipeline/models/image_snapshot.py` — ImageSnapshot ORM 模型
    - 字段：id, project_id(FK), asin, image_url, image_hash(sha256), captured_at(datetime), slot_position(int)
  - 新建 `pipeline/layers/change_detector.py`:
    - `capture_snapshot(project_id, asin, image_url, slot_position)` — 下载图片，计算 hash，存入 DB
    - `detect_changes(project_id, asin)` — 对比最新两次快照的 hash，返回变更列表
    - `get_change_history(project_id, asin)` — 查询变更历史
  - Web: GET `/project/<id>/changes` — 变更历史展示
  - **TDD**: `tests/test_change_detector.py`

  **Must NOT do**:
  - 不实现定时自动检测（仅提供手动触发接口）
  - 图片 hash 用 sha256（不引入 perceptual hash 库）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 涉及图片下载和 hash 计算
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with Tasks 14, 16)
  - **Blocks**: Task F1-F4
  - **Blocked By**: Task 0 (schema)

  **References**:
  - `pipeline/layers/vision_analyzer.py` — 图片处理模式参考
  - 路线图：「主图变更检测」章节

  **Acceptance Criteria**:
  - [ ] `tests/test_change_detector.py` 存在且 PASS
  - [ ] `capture_snapshot()` 计算并存储 sha256 hash
  - [ ] 两次不同图片 → `detect_changes()` 返回 changed 条目
  - [ ] 两次相同图片 → `detect_changes()` 返回空列表

  **QA Scenarios**:

  ```
  Scenario: 检测图片变更
    Tool: Bash
    Steps:
      1. capture_snapshot(1, 'B0XXX', 'path/img1.jpg', 0)
      2. capture_snapshot(1, 'B0XXX', 'path/img2.jpg', 0)  # 不同图片
      3. detect_changes(1, 'B0XXX')
    Expected Result: 返回含 slot_position=0 的变更记录
    Evidence: .sisyphus/evidence/task-15-change-detect.txt
  ```

  **Commit**: `feat(layers): add hero image change detection`

- [ ] 16. 跨项目知识库

  **What to do**:
  - 新建 `pipeline/models/knowledge_entry.py` — KnowledgeEntry ORM 模型
    - 字段：id, source_project_id(FK), category(ENUM: prompt_pattern/qa_lesson/style_rule/client_preference), title, content(text), tags(text, comma-separated), created_at, usage_count(int, default=0)
  - 新建 `pipeline/layers/knowledge_base.py`:
    - `add_entry(source_project_id, category, title, content, tags)` — 新增知识条目
    - `search_entries(query, category=None, limit=10)` — 按关键词搜索（title + content LIKE 匹配）
    - `get_popular_entries(category=None, limit=10)` — 按 usage_count 排序
    - `increment_usage(entry_id)` — 使用计数+1
  - Web: GET `/knowledge` — 知识库浏览页面（分类筛选 + 搜索框）
  - **TDD**: `tests/test_knowledge_base.py`

  **Must NOT do**:
  - 不引入向量数据库或 embedding（纯 SQL LIKE 搜索）
  - 不引入全文索引

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单 CRUD + LIKE 搜索
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with Tasks 14, 15)
  - **Blocks**: Task F1-F4
  - **Blocked By**: Task 0 (schema)

  **References**:
  - `pipeline/models/project.py` — ORM 模式
  - `pipeline/web/app.py` — Flask 路由模式
  - 路线图：「跨项目知识库」章节

  **Acceptance Criteria**:
  - [ ] `tests/test_knowledge_base.py` 存在且 PASS
  - [ ] `add_entry(1, 'prompt_pattern', 'Studio Lighting', 'use soft..', 'lighting')` 写入 DB
  - [ ] `search_entries('lighting')` 返回匹配条目
  - [ ] GET `/knowledge` 返回200

  **QA Scenarios**:

  ```
  Scenario: 添加并搜索知识条目
    Tool: Bash
    Steps:
      1. PYTHONPATH=. python -c "from pipeline.layers.knowledge_base import add_entry, search_entries; add_entry(1, 'prompt_pattern', 'Studio Light', 'soft box setup', 'lighting,studio'); print(search_entries('studio'))"
    Expected Result: 返回含 'Studio Light' 条目的列表
    Evidence: .sisyphus/evidence/task-16-knowledge-search.txt
  ```

  **Commit**: `feat(layers): add cross-project knowledge base`

- [ ] 17. ImageSlot 清理

  **What to do**:
  - 确认 `pipeline/models/image_slot.py` 仅被测试文件引用（已验证：仅 2 个测试文件 + 模型文件自身）
  - 删除 `pipeline/models/image_slot.py`
  - 删除测试文件中对 ImageSlot 的 import 和使用（替换为 SlotPlan 或移除无用测试）
  - 从 `models/__init__.py` 移除 ImageSlot 导出（如有）
  - 运行全量测试确认无回归
  - **TDD**: 先确认删除后测试全绿

  **Must NOT do**:
  - 不引入新模型替代（SlotPlan 已存在）
  - 不修改任何非 ImageSlot 相关代码

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单删除 + import 清理
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 6 (solo, after all other tasks)
  - **Blocks**: Task F1-F4
  - **Blocked By**: All Tasks 0-16

  **References**:
  - `pipeline/models/image_slot.py` — 待删除文件
  - `tests/` — grep ImageSlot 找到引用的测试文件
  - `pipeline/models/__init__.py` — 可能有导出

  **Acceptance Criteria**:
  - [ ] `pipeline/models/image_slot.py` 不存在
  - [ ] `grep -r 'ImageSlot' pipeline/ tests/` 无匹配
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/ -q` 全绿

  **QA Scenarios**:

  ```
  Scenario: ImageSlot 完全清除
    Tool: Bash
    Steps:
      1. grep -r 'ImageSlot' pipeline/ tests/
      2. PYTHONPATH=. .venv/bin/pytest tests/ -q
    Expected Result: grep 无匹配（exit 1），pytest 全绿
    Evidence: .sisyphus/evidence/task-17-cleanup.txt
  ```

  **Commit**: `chore(models): remove deprecated ImageSlot model`

---

## Final Verification Wave (MANDATORY)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [ ] F1. **Plan Compliance Audit** — `oracle`
      Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, curl endpoint, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
      Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
      Run `PYTHONPATH=. .venv/bin/pytest tests/ -q`. Review all changed files for: `as any`, empty catches, `print()` in prod, commented-out code, unused imports, `<style>` inline CSS. Check AI slop: excessive comments, over-abstraction, generic names.
      Output: `Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high` (+ `playwright` skill)
      Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration. Test edge cases: empty state, invalid input, rapid actions. Save to `.sisyphus/evidence/final-qa/`.
      Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
      For each task: read "What to do", read actual diff (git log/diff). Verify 1:1. Check "Must NOT do" compliance. Detect cross-task contamination. Flag unaccounted changes.
      Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

每个 task 独立原子提交：

- **Task 0**: `fix(models): extend APlusContent and TagAssignment schemas for L4`
- **Task 1**: `feat(web): add guided customer input UI`
- **Task 2**: `feat(web): add asset upload UI with drag-and-drop`
- **Task 3**: `feat(web): add brand profile card UI`
- **Task 4**: `feat(layers): implement A+ content generation logic`
- **Task 5**: `feat(layers): implement 3-layer tag system`
- **Task 6**: `feat(layers): implement reference pack 6 components`
- **Task 7**: `feat(layers): implement consistency lock system`
- **Task 8**: `feat(qa): implement all 5 QA gate hard checks`
- **Task 9**: `feat(delivery): complete delivery package 5 items`
- **Task 10**: `feat(web): add customer feedback UI`
- **Task 11**: `feat(layers): add version management with diff and rollback`
- **Task 12**: `feat(layers): add revision decision lookup table`
- **Task 13**: `feat(web): add prompt editor UI`
- **Task 14**: `feat(layers): add ASIN ranking tracker`
- **Task 15**: `feat(layers): add hero image change detection`
- **Task 16**: `feat(layers): add cross-project knowledge base`
- **Task 17**: `chore(models): remove deprecated ImageSlot model`

---

## Success Criteria

### Verification Commands

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q  # Expected: 280+ passed, 0 failed
PYTHONPATH=. python -m pipeline.__main__ run --project-id 1  # Expected: full pipeline completes
curl http://localhost:5000/input/new  # Expected: 200, guided input form
curl http://localhost:5000/brand-profile/1  # Expected: 200, 10-dimension card
```

### Final Checklist

- [ ] 17/17 路线图 L4 任务已实现
- [ ] 280+ tests 全绿
- [ ] 所有 Must Have 已验证
- [ ] 所有 Must NOT Have 未违反
- [ ] 所有 QA scenarios evidence 文件已生成
