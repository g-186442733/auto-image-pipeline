# Single Admin Mode — 去掉登录，按客户区分显示

## TL;DR

> **Quick Summary**: 将 auto-image-pipeline 从多租户隔离模式改为单管理员模式。去掉登录认证，移除 56 处 tenant_id 过滤，管理员看到所有客户数据，界面上显示客户归属并支持筛选。
>
> **Deliverables**:
>
> - 无需登录即可访问所有页面
> - 项目/品牌/审核/交付页面显示客户名列 + 客户筛选
> - 新建项目时搜索式选择客户或创建新客户
> - 客户管理页 `/customers`
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 4 waves
> **Critical Path**: Task 1 → Tasks 2,3 → Tasks 4,5,6 → Task 7

---

## Context

### Original Request

老板要求把系统从多租户 SaaS 模式改为单管理员模式。当前阶段不需要租户登录隔离，老板本地跑，直接管理所有客户的项目和品牌。界面上按客户区分显示和筛选。

### Interview Summary

**Key Discussions**:

- 不需要登录页，本地跑无需认证
- 默认显示全部客户数据，支持按客户筛选
- 新建项目时搜索式选择已有客户或创建新客户
- 品牌三层（Tenant→CustomerProfile→BrandProfile→ProductProfile）不变
- 56 处 tenant_id 过滤全部定位（app.py 46 处 + routes/ 10 处）

**Research Findings**:

- 模板文件中无 `g.tenant` 或 `current_user` 引用，auth 移除不影响模板
- Tenant 表已有 `name`, `slug` 字段，可直接复用为"客户"实体
- `before_request` hook 负责设置 `g.tenant_id`，移除后需处理所有引用点

### Metis Review

**Identified Gaps** (addressed):

- `g.tenant_id` 移除后需替换为函数参数传递或移除 — 逐处处理
- 数据库表和列名保持不变（`tenants` 表、`tenant_id` 列），只改代码逻辑
- 新记录仍需写入 `tenant_id`（通过客户选择器获得）
- 客户不可删除（防止孤儿项目）

---

## Work Objectives

### Core Objective

移除登录认证和租户隔离过滤，让管理员直接访问所有数据，界面上按客户区分显示。

### Concrete Deliverables

- `app.py`: 移除 login 路由、`@login_required` 装饰器、`before_request` auth hook
- `app.py` + `routes/*.py`: 移除 56 处 tenant_id 过滤
- 项目列表页: 新增客户名列 + 客户下拉筛选
- 新建项目表单: 搜索式客户选择器（搜索已有 / 新建）
- `/customers` 页面: 客户列表 + 新增
- 品牌/审核/交付页面: 显示客户名

### Definition of Done

- [ ] `curl http://localhost:9010/` 返回 200（不跳转登录）
- [ ] 项目列表显示所有客户的项目（数量与数据库一致）
- [ ] 47/47 现有单元测试通过
- [ ] 所有页面无 500 错误

### Must Have

- 无需登录即可访问
- 所有页面默认显示全部数据
- 客户名在关键页面可见
- 客户筛选功能
- 新建项目时客户选择/创建

### Must NOT Have (Guardrails)

- ❌ 不修改 `/input/new` 和 `/input/<id>/edit` 路由逻辑
- ❌ 不修改 `customer_input.html`
- ❌ 不重命名数据库表或列（`tenants` 表、`tenant_id` 列保持原名）
- ❌ 不新建数据库表（复用 `tenants` 表）
- ❌ 不碰品牌三层层级逻辑（CustomerProfile/BrandProfile/ProductProfile）
- ❌ 不加分页、排序等超出范围的 UI 改进
- ❌ 不加任何新的认证/授权机制
- ❌ 不用 `<style>` 内联 CSS，样式写 `style.css`
- ❌ 不用 `nohup` 启动服务，只用 `launchctl kickstart -k`
- ❌ 不用 Alembic，只用 `db_migrate.py`

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed.

### Test Decision

- **Infrastructure exists**: YES（47 个单元测试已通过）
- **Automated tests**: Tests-after（改完跑现有测试确认不 break）
- **Framework**: pytest + Playwright E2E

### QA Policy

每个任务完成后：

1. 运行 `pytest` 确认现有测试不 break
2. `curl` 验证页面返回 200
3. 重启服务验证：`launchctl kickstart -k gui/$(id -u)/com.axureboutique.auto-image-pipeline`

Evidence 保存到 `.sisyphus/evidence/task-{N}-*.txt`

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately):
└── Task 1: Remove auth system [deep]

Wave 2 (After Wave 1 — PARALLEL):
├── Task 2: Remove tenant_id filtering in app.py (46 locations) [deep]
└── Task 3: Remove tenant_id filtering in routes/ (10 locations) [quick]

Wave 3 (After Wave 2 — PARALLEL):
├── Task 4: Customer name column + filter on project list [quick]
├── Task 5: Customer search/create selector for new project [quick]
└── Task 6: Customer management page /customers [quick]

Wave 4 (After Wave 3):
└── Task 7: Customer labels on brand/review/delivery pages [quick]

Wave FINAL (After ALL tasks — 4 parallel reviews):
├── F1: Plan compliance audit (oracle)
├── F2: Code quality review (unspecified-high)
├── F3: Real QA (unspecified-high + playwright)
└── F4: Scope fidelity check (deep)
→ Present results → Get user okay
```

### Dependency Matrix

| Task | Depends On | Blocks     |
| ---- | ---------- | ---------- |
| 1    | —          | 2, 3       |
| 2    | 1          | 4, 5, 6, 7 |
| 3    | 1          | 4, 5, 6, 7 |
| 4    | 2, 3       | 7          |
| 5    | 2, 3       | —          |
| 6    | 2, 3       | —          |
| 7    | 4          | —          |

### Agent Dispatch Summary

- **Wave 1**: 1 task — T1 → `deep`
- **Wave 2**: 2 tasks — T2 → `deep`, T3 → `quick`
- **Wave 3**: 3 tasks — T4,T5,T6 → `quick`
- **Wave 4**: 1 task — T7 → `quick`
- **FINAL**: 4 tasks — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [x] 1. Remove auth system (login, login_required, before_request auth)

  **What to do**:
  - Delete the `login` and `logout` routes from `app.py`
  - Delete `login_required` decorator definition (app.py L133-160) and remove ALL `@login_required` decorations (~20 occurrences in app.py + routes/)
  - Delete/simplify the two `before_request` hooks (app.py L127, L164) that set `g.tenant_id` — remove the auth/redirect logic entirely
  - Remove all references to `g.tenant_id` assignment (but NOT the `tenant_id` column usage — that's Task 2/3)
  - Delete `templates/login.html`
  - Remove login/logout links from `templates/base.html` nav, add `/customers` link instead
  - Remove `session` imports and `session.clear()` calls related to auth
  - Keep the Flask `session` import if used elsewhere; remove only auth-specific usage

  **Must NOT do**:
  - Do NOT modify `/input/new` or `/input/<id>/edit` route logic
  - Do NOT modify `customer_input.html`
  - Do NOT remove `tenants` table or `tenant_id` columns

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 20+ scattered removal points across app.py (1592 lines), requires careful tracing of auth flow
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1 (solo)
  - **Blocks**: Tasks 2, 3
  - **Blocked By**: None

  **References**:
  - `pipeline/web/app.py:127` — first `before_request` hook (auth check)
  - `pipeline/web/app.py:133-160` — `login_required` decorator definition
  - `pipeline/web/app.py:164` — second `before_request` hook (tenant setup)
  - `pipeline/web/templates/login.html` — to delete
  - `pipeline/web/templates/base.html` — nav bar login/logout links to remove

  **Acceptance Criteria**:
  - [ ] `grep -r 'login_required\|def login\|session\[.tenant.\]' pipeline/web/app.py pipeline/web/routes/` returns 0 matches
  - [ ] `ls pipeline/web/templates/login.html` → file not found
  - [ ] `curl -s -o /dev/null -w '%{http_code}' http://localhost:9010/` → 200 (no redirect to /login)
  - [ ] `python -m pytest` → all pass

  **QA Scenarios**:

  ```
  Scenario: Homepage loads without auth
    Tool: Bash (curl)
    Preconditions: Service running on port 9010
    Steps:
      1. curl -sL -o /dev/null -w '%{http_code}' http://localhost:9010/
      2. Assert response code is 200
    Expected Result: 200 (not 302 redirect to /login)
    Evidence: .sisyphus/evidence/task-1-no-auth-redirect.txt

  Scenario: /login returns 404
    Tool: Bash (curl)
    Preconditions: Service running
    Steps:
      1. curl -s -o /dev/null -w '%{http_code}' http://localhost:9010/login
      2. Assert 404
    Expected Result: 404
    Evidence: .sisyphus/evidence/task-1-login-404.txt
  ```

  **Commit**: YES
  - Message: `refactor(auth): remove login system and tenant isolation`
  - Files: `pipeline/web/app.py`, `pipeline/web/routes/*.py`, `pipeline/web/templates/base.html`
  - Pre-commit: `pytest`

- [x] 2. Remove tenant_id filtering in app.py (46 locations)

  **What to do**:
  - Find all 46 occurrences of `.filter(*.tenant_id == ...)` or `.filter_by(tenant_id=...)` in `app.py`
  - Remove each filter clause. If it's the only filter, remove the entire `.filter()` call. If chained, remove just the tenant_id condition.
  - For INSERT/create operations: keep `tenant_id` field but source it from the form/request data instead of `g.tenant_id` (this will be wired in Task 5)
  - Temporarily hardcode `tenant_id=1` for create operations if no customer selector is available yet (Task 5 will fix this)

  **Must NOT do**:
  - Do NOT modify `/input/new` or `/input/<id>/edit` route logic
  - Do NOT remove `tenant_id` column from models
  - Do NOT remove tenant_id from INSERT statements — just change the source

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 46 scattered locations in a 1592-line file, each needs context-aware removal
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Task 3)
  - **Blocks**: Tasks 4, 5, 6, 7
  - **Blocked By**: Task 1

  **References**:
  - `pipeline/web/app.py` — all 46 locations (search `.filter.*tenant_id` and `.filter_by.*tenant_id`)
  - `pipeline/models/project.py` — Project model has `tenant_id` FK

  **Acceptance Criteria**:
  - [ ] `grep -c 'tenant_id.*==.*g\.\|g\.tenant_id\|filter.*tenant_id' pipeline/web/app.py` → 0
  - [ ] `python -m pytest` → all pass
  - [ ] `curl -s -o /dev/null -w '%{http_code}' http://localhost:9010/projects` → 200

  **QA Scenarios**:

  ```
  Scenario: Project list shows ALL projects (no tenant filtering)
    Tool: Bash (curl)
    Preconditions: Service running, DB has projects across multiple tenants
    Steps:
      1. curl -s http://localhost:9010/projects | grep -c 'project-row'
      2. Compare count with: python -c "from pipeline.models import *; from pipeline.db import get_session; s=get_session(); print(s.query(Project).count())"
    Expected Result: Counts match — all projects visible
    Evidence: .sisyphus/evidence/task-2-all-projects-visible.txt

  Scenario: No g.tenant_id references remain
    Tool: Bash (grep)
    Steps:
      1. grep -rn 'g\.tenant_id' pipeline/web/app.py
    Expected Result: 0 matches
    Evidence: .sisyphus/evidence/task-2-no-tenant-refs.txt
  ```

  **Commit**: YES (groups with Task 3)
  - Message: `refactor(queries): remove tenant_id filtering from all queries`
  - Files: `pipeline/web/app.py`, `pipeline/web/routes/*.py`
  - Pre-commit: `pytest`

- [x] 3. Remove tenant_id filtering in routes/ (10 locations)

  **What to do**:
  - Remove tenant_id filtering from:
    - `routes/tag_review_routes.py` — 4 occurrences
    - `routes/decision_routes.py` — 1 occurrence
    - `routes/hypothesis_routes.py` — 4 occurrences
    - `routes/project_routes.py` — 1 occurrence
  - Same logic as Task 2: remove filter clauses, keep tenant_id in INSERTs

  **Must NOT do**:
  - Do NOT modify `/input/new` or `/input/<id>/edit` route logic
  - Do NOT modify `customer_input.html`

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Task 2)
  - **Blocks**: Tasks 4, 5, 6, 7
  - **Blocked By**: Task 1

  **References**:
  - `pipeline/web/routes/tag_review_routes.py` — 4 filter locations
  - `pipeline/web/routes/decision_routes.py` — 1 filter location
  - `pipeline/web/routes/hypothesis_routes.py` — 4 filter locations
  - `pipeline/web/routes/project_routes.py` — 1 filter location

  **Acceptance Criteria**:
  - [ ] `grep -rc 'g\.tenant_id\|filter.*tenant_id' pipeline/web/routes/` → 0
  - [ ] `python -m pytest` → all pass

  **QA Scenarios**:

  ```
  Scenario: No tenant filtering in routes/
    Tool: Bash (grep)
    Steps:
      1. grep -rn 'g\.tenant_id\|filter.*tenant_id' pipeline/web/routes/
    Expected Result: 0 matches
    Evidence: .sisyphus/evidence/task-3-routes-clean.txt
  ```

  **Commit**: YES (groups with Task 2)
  - Message: `refactor(queries): remove tenant_id filtering from all queries`
  - Pre-commit: `pytest`

- [x] 4. Customer name column + filter on project list

  **What to do**:
  - In `templates/index.html` (project list page):
    - Add a "客户" column header to the project table
    - For each project row, display `project.tenant.name`
    - Add a customer dropdown filter above the table (populated from all tenants)
    - JS: filter table rows on dropdown change; "全部" option shows all
  - In `app.py` project list route: ensure query joins/eager-loads tenant for name access
  - Add styles to `static/style.css` for the filter dropdown and customer column

  **Must NOT do**:
  - No pagination, sorting, or other UI additions beyond the customer filter

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 5, 6)
  - **Blocks**: Task 7
  - **Blocked By**: Tasks 2, 3

  **References**:
  - `pipeline/web/templates/index.html` — current project list table
  - `pipeline/web/app.py` — project list route
  - `pipeline/models/tenant.py` — Tenant.name field
  - `pipeline/web/static/style.css` — add filter styles here

  **Acceptance Criteria**:
  - [ ] Project list page shows "客户" column with tenant names
  - [ ] Dropdown filter shows all unique customer names + "全部"
  - [ ] Selecting a customer filters the table; "全部" shows all

  **QA Scenarios**:

  ```
  Scenario: Customer column visible
    Tool: Playwright
    Steps:
      1. Navigate to http://localhost:9010/projects
      2. Assert table header contains text "客户"
      3. Assert at least one row shows a customer name
    Expected Result: Column exists with data
    Evidence: .sisyphus/evidence/task-4-customer-column.png

  Scenario: Customer filter works
    Tool: Playwright
    Steps:
      1. Navigate to http://localhost:9010/projects
      2. Note total row count
      3. Select a specific customer from filter dropdown
      4. Assert visible rows show only that customer
      5. Select "全部", assert all rows visible again
    Expected Result: Filter correctly shows/hides rows
    Evidence: .sisyphus/evidence/task-4-filter-works.png
  ```

  **Commit**: YES
  - Message: `feat(ui): add customer column and filter to project list`
  - Pre-commit: `pytest`

- [x] 5. Customer search/create selector for new project form

  **What to do**:
  - In the new project creation form template:
    - Add a search-style customer selector: type to search existing customers, select one; or type new name and click "新建客户"
    - On submit, send `tenant_id` (or `new_customer_name` to create on the fly)
  - In `app.py` project creation route:
    - Accept `tenant_id` from form POST data
    - If `new_customer_name` provided, create new Tenant first, use its ID
  - Add `/api/customers/search` endpoint returning JSON for autocomplete
  - Styles in `style.css`

  **Must NOT do**:
  - Do NOT modify `/input/new` or `/input/<id>/edit` route logic
  - Do NOT modify `customer_input.html`

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 4, 6)
  - **Blocks**: None
  - **Blocked By**: Tasks 2, 3

  **References**:
  - `pipeline/web/app.py` — project creation route
  - `pipeline/models/tenant.py` — Tenant model
  - The project creation template (find via route's `render_template` call)

  **Acceptance Criteria**:
  - [ ] New project form shows customer search field
  - [ ] Typing filters existing customers
  - [ ] Creating new customer inline works

  **QA Scenarios**:

  ```
  Scenario: Search and select existing customer
    Tool: Playwright
    Steps:
      1. Navigate to project creation page
      2. Type first 2 chars of known customer name in search field
      3. Assert dropdown shows matching customer(s)
      4. Click to select, submit form
      5. Assert new project created with correct tenant_id
    Expected Result: Project linked to selected customer
    Evidence: .sisyphus/evidence/task-5-search-select.png

  Scenario: Create new customer inline
    Tool: Playwright
    Steps:
      1. Navigate to project creation page
      2. Type unique new customer name
      3. Click "新建客户" button, submit form
      4. Navigate to /customers and verify new customer appears
    Expected Result: New customer created and linked
    Evidence: .sisyphus/evidence/task-5-create-inline.png
  ```

  **Commit**: YES
  - Message: `feat(ui): add customer search/create selector for new project`
  - Pre-commit: `pytest`

- [x] 6. Customer management page /customers

  **What to do**:
  - Create new route `GET /customers` in `app.py` — lists all tenants
  - Create `templates/customers.html` — table of customers (name, slug, project count, created date)
  - Add inline "新增客户" form at top (name + slug fields, POST to `/customers/new`)
  - Create `POST /customers/new` route — creates new Tenant record
  - Customer deletion NOT supported (guardrail: prevent orphan projects)
  - Add styles to `style.css`

  **Must NOT do**:
  - No customer deletion
  - No customer editing (keep it simple for now)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 4, 5)
  - **Blocks**: None
  - **Blocked By**: Tasks 2, 3

  **References**:
  - `pipeline/models/tenant.py` — Tenant model (name, slug, plan fields)
  - `pipeline/web/templates/base.html` — nav template to add /customers link
  - `pipeline/web/templates/index.html` — table styling pattern to follow

  **Acceptance Criteria**:
  - [ ] `curl -s -o /dev/null -w '%{http_code}' http://localhost:9010/customers` → 200
  - [ ] Page shows list of all customers with project counts
  - [ ] Can add new customer via the form

  **QA Scenarios**:

  ```
  Scenario: Customer list page loads
    Tool: Playwright
    Steps:
      1. Navigate to http://localhost:9010/customers
      2. Assert page title/heading contains "客户"
      3. Assert table has at least 1 row
    Expected Result: Page loads with customer data
    Evidence: .sisyphus/evidence/task-6-customer-list.png

  Scenario: Add new customer
    Tool: Playwright
    Steps:
      1. Navigate to /customers
      2. Fill name field with "测试客户ABC"
      3. Fill slug field with "test-abc"
      4. Click submit
      5. Assert "测试客户ABC" appears in customer table
    Expected Result: New customer created and visible
    Evidence: .sisyphus/evidence/task-6-add-customer.png
  ```

  **Commit**: YES
  - Message: `feat(customers): add customer management page`
  - Pre-commit: `pytest`

- [x] 7. Customer labels on brand/review/delivery pages

  **What to do**:
  - Identify all pages that list brands, reviews, or deliveries
  - Add customer name display (e.g., badge or column) showing which customer each item belongs to
  - Ensure tenant relationship is eager-loaded in relevant queries
  - Add customer filter dropdown where appropriate (same pattern as Task 4)

  **Must NOT do**:
  - Do NOT modify `/input/new` or `/input/<id>/edit`
  - Do NOT modify `customer_input.html`

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 4 (solo)
  - **Blocks**: None
  - **Blocked By**: Task 4

  **References**:
  - `pipeline/web/app.py` — brand list, review, delivery routes
  - `pipeline/web/templates/` — corresponding templates for these pages
  - Task 4 implementation — follow same column + filter pattern

  **Acceptance Criteria**:
  - [ ] Brand list page shows customer name per brand
  - [ ] Review page shows customer name per item
  - [ ] Delivery page shows customer name per item

  **QA Scenarios**:

  ```
  Scenario: Customer name visible on brand page
    Tool: Playwright
    Steps:
      1. Navigate to brand list page
      2. Assert customer name is visible for at least one brand entry
    Expected Result: Customer attribution visible
    Evidence: .sisyphus/evidence/task-7-brand-customer.png

  Scenario: Customer name visible on review page
    Tool: Playwright
    Steps:
      1. Navigate to review page
      2. Assert customer name visible
    Expected Result: Customer attribution visible
    Evidence: .sisyphus/evidence/task-7-review-customer.png
  ```

  **Commit**: YES
  - Message: `feat(ui): add customer labels to brand/review/delivery pages`
  - Pre-commit: `pytest`

---

## Final Verification Wave

> 4 review agents run in PARALLEL. ALL must APPROVE.

- [ ] F1. **Plan Compliance Audit** — `oracle`
      Read the plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search codebase for forbidden patterns. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
      Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
      Run `pytest`. Review all changed files for: `as any`, empty catches, console.log in prod, commented-out code, unused imports. Check no `g.tenant_id` or `login_required` references remain. Check no `<style>` tags in templates.
      Output: `Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real QA** — `unspecified-high` (+ `playwright` skill)
      Start from clean state. Restart service via launchctl. Verify every page loads (/, /projects, /customers, brand list, review, delivery). Create new project with existing customer. Create new project with new customer. Filter by customer. Capture screenshots.
      Output: `Pages [N/N load] | Flows [N/N pass] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
      For each task: read "What to do", read actual `git diff`. Verify nothing beyond scope was built. Check `/input/new`, `/input/<id>/edit`, `customer_input.html` are UNTOUCHED. Check no DB schema changes beyond what's planned.
      Output: `Tasks [N/N compliant] | Exclusions [CLEAN/N issues] | VERDICT`

---

## Commit Strategy

| Commit | Scope                            | Pre-commit    |
| ------ | -------------------------------- | ------------- |
| 1      | Task 1: Remove auth              | `pytest` pass |
| 2      | Tasks 2+3: Remove tenant filters | `pytest` pass |
| 3      | Task 4: Customer column + filter | `pytest` pass |
| 4      | Task 5: Customer selector        | `pytest` pass |
| 5      | Task 6: Customer management page | `pytest` pass |
| 6      | Task 7: Customer labels          | `pytest` pass |

---

## Success Criteria

### Verification Commands

```bash
curl -s -o /dev/null -w '%{http_code}' http://localhost:9010/  # Expected: 200
curl -s -o /dev/null -w '%{http_code}' http://localhost:9010/projects  # Expected: 200
curl -s -o /dev/null -w '%{http_code}' http://localhost:9010/customers  # Expected: 200
cd /Users/axureboutique/Projects/auto-image-pipeline && python -m pytest  # Expected: 47 passed
grep -r 'login_required\|g\.tenant_id' pipeline/web/app.py pipeline/web/routes/ | wc -l  # Expected: 0
grep -r '<style>' pipeline/web/templates/ | wc -l  # Expected: 0
```

### Final Checklist

- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All tests pass
- [ ] All pages load without error
- [ ] Customer display and filtering works
