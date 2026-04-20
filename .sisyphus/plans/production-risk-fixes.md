# Production Risk Fixes — 静默异常修复 + Mock Fallback 删除

## TL;DR

> **Quick Summary**: 修复生产风险审计发现的所有静默异常吞掉（`except: pass`）和 mock data fallback，确保 AI 调用失败时 raise 而非静默回退假数据，optional enrichment 失败时 log.warning，数据完整性操作失败时 raise。
>
> **Deliverables**:
>
> - 6 个 🔴 高风险修复（amazon_data, brief_generator, aplus_generator, delivery）
> - 3 个 🟡 中风险修复（tag_system, slot_planner, qa_gate）
> - 所有受影响测试更新，基线 ≥ 631 passed
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Wave 1 (all parallel) → Wave 2 (test updates) → Final Verification

---

## Context

### Original Request

老板要求对 `pipeline/` 全面扫描静默异常吞掉（`except Exception: pass`）和 mock data fallback，识别生产风险并统一修复。审计已完成，发现 9 个需修复点（6 🔴 + 3 🟡），老板已逐一确认修复策略。

### 修复原则（老板确认）

1. **AI 调用（Gemini）失败 → raise**，让 orchestrator 处理
2. **Optional enrichment（KB, CustomerBrief）失败 → `log.warning` + 继续**（不 raise，不 pass）
3. **数据完整性操作失败 → raise**
4. **Orchestrator 的 log-and-continue → 保持不变**（各层 raise，orchestrator catch 并决策）

### 不修的项（老板确认）

- `feedback_loop.py` 4 处：已经是 `rollback() + raise`，正确 ✅
- `db_migrate.py` 6 处：幂等迁移设计 ✅
- `qa_gate.py:352,658` JSON 解析 optional notes ✅
- `slot_planner.py:35-44` brief JSON tag 解析 ✅
- `hypothesis_routes.py:78` float conversion ✅
- `helium10_adapter.py` 桩实现 ✅
- Orchestrator log-and-continue ✅

---

## Work Objectives

### Core Objective

消除所有静默异常吞掉，确保流水线中 AI 生成失败、数据查询失败时有明确的错误信号。

### Concrete Deliverables

- 修改 7 个文件中的 9 处异常处理
- 更新所有受影响测试

### Definition of Done

- [ ] `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py` → ≥ 631 passed, 0 failed

### Must Have

- API/AI 调用失败时 raise 异常（不返回默认值）
- Optional enrichment 失败时 `log.warning`（不是静默 pass）

### Must NOT Have (Guardrails)

- 不改 orchestrator.py 的异常处理逻辑
- 不改 db_migrate.py
- 不引入新依赖
- 不改 feedback_loop.py（已正确）

---

## Verification Strategy

### Test Decision

- **Infrastructure exists**: YES
- **Automated tests**: YES (tests-after)
- **Framework**: pytest
- **Command**: `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py`

### QA Policy

每个 task 修改后运行测试，确保 ≥ 631 passed。

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (All parallel — 源码修改):
├── Task 1: amazon_data.py — 删除 mock fallback [quick]
├── Task 2: brief_generator.py — 4处异常修复 [quick]
├── Task 3: aplus_generator.py — Gemini 失败 raise [quick]
├── Task 4: delivery.py — version 创建失败 raise [quick]
├── Task 5: tag_system.py — AI 标签失败 log.warning [quick]
├── Task 6: slot_planner.py — KB 查询失败 log.warning [quick]
└── Task 7: qa_gate.py — 图片尺寸读取失败 log.warning [quick]

Wave 2 (After Wave 1 — 测试更新):
└── Task 8: 更新所有受影响测试 [unspecified-high]

Wave FINAL (After ALL — 验证):
└── Task 9: 运行全量测试 + 回归验证 [quick]
```

---

## TODOs

- [ ] 1. amazon_data.py — 删除 mock fallback, API 失败 raise

  **What to do**:
  - 删除 `_mock_reviews()` 函数（L238-249）
  - 删除 `_mock_qa()` 函数（L251-265）
  - `fetch_reviews()` 中所有 `return _mock_reviews(asin)` 改为 `raise KeepaDataError(f"Keepa API failed for {asin}: no reviews")`
  - `fetch_qa()` 中所有 `return _mock_qa(asin)` 改为 `raise KeepaDataError(f"Keepa API failed for {asin}: no Q&A")`
  - `return results or _mock_reviews(asin)` → `if not results: raise KeepaDataError(...)` / `return results`
  - 同理 `return results or _mock_qa(asin)`
  - 在文件顶部定义 `class KeepaDataError(Exception): pass`（如不存在）

  **Must NOT do**: 不改 Keepa API 调用逻辑本身

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 8
  - **Blocked By**: None

  **References**:
  - `pipeline/layers/amazon_data.py:238-265` — mock 函数定义
  - `pipeline/layers/amazon_data.py:279,284,289,304,324,329,334,347` — 所有 mock 调用点
  - `.sisyphus/plans/remove-mock-fallback.md` — 旧计划中有更详细的上下文

  **Acceptance Criteria**:
  - [ ] `_mock_reviews` 和 `_mock_qa` 函数不再存在
  - [ ] grep `_mock_reviews\|_mock_qa` 在 amazon_data.py 中返回 0 结果
  - [ ] `KeepaDataError` 已定义

  **QA Scenarios**:

  ```
  Scenario: grep 验证 mock 已删除
    Tool: Bash
    Steps:
      1. grep -c "_mock_reviews\|_mock_qa" pipeline/layers/amazon_data.py
    Expected Result: 0（或 command exit 1 = no matches）
    Evidence: .sisyphus/evidence/task-1-mock-removed.txt

  Scenario: KeepaDataError 已定义
    Tool: Bash
    Steps:
      1. grep "class KeepaDataError" pipeline/layers/amazon_data.py
    Expected Result: 匹配到定义行
    Evidence: .sisyphus/evidence/task-1-error-class.txt
  ```

  **Commit**: YES (group with Task 2-7)
  - Message: `fix(pipeline): remove silent exception swallowing and mock fallbacks`
  - Files: `pipeline/layers/amazon_data.py`

- [ ] 2. brief_generator.py — 4 处异常修复

  **What to do**:
  - **L75-84** (KB search_entries 失败): `except Exception: pass` → `except Exception: log.warning("KB search failed for project %s, skipping enrichment", project_id)`
  - **L97-105** (CustomerBrief 查询失败): `except Exception: pass` → `except Exception: log.warning("CustomerBrief query failed for project %s, skipping", project_id)`
  - **L108-114** (Gemini 调用失败 → 使用 \_DEFAULT_BRIEF): 删除 `_DEFAULT_BRIEF` 回退。`except Exception` → `raise`（让 orchestrator 处理）。即：移除 `brief_json = _DEFAULT_BRIEF` 初始赋值，try 块中直接 `raw = _call_gemini(prompt)` → 解析 → 赋值，失败时 raise。
  - **L117-121** (JSON 解析失败 → 空 slots): `except Exception: pass` → `except json.JSONDecodeError as e: raise ValueError(f"Gemini returned invalid JSON for project {project_id}: {e}") from e`

  **Must NOT do**: 不改 `_call_gemini` 函数本身

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 8
  - **Blocked By**: None

  **References**:
  - `pipeline/layers/brief_generator.py:73-125` — 所有 4 处异常
  - 注意 `log` 对象名称：检查文件顶部是 `log = logging.getLogger(...)` 还是 `logger = ...`

  **Acceptance Criteria**:
  - [ ] grep `except Exception:\s*$` + 下一行 `pass` 在 brief_generator.py 中返回 0 结果
  - [ ] `_DEFAULT_BRIEF` 不再作为 fallback 使用（可保留常量定义但不在 except 中引用）

  **QA Scenarios**:

  ```
  Scenario: 无静默 pass 残留
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/python -c "import ast; tree=ast.parse(open('pipeline/layers/brief_generator.py').read()); handlers=[n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and len(n.body)==1 and isinstance(n.body[0], ast.Pass)]; print(len(handlers))"
    Expected Result: 0
    Evidence: .sisyphus/evidence/task-2-no-silent-pass.txt
  ```

  **Commit**: YES (group with Task 1, 3-7)

- [ ] 3. aplus_generator.py — Gemini 失败 raise

  **What to do**:
  - **L104-113**: 移除 `modules_data = _DEFAULT_MODULES` 初始赋值。`try` 块中 Gemini 调用失败时 raise 而非 fall through 到 `_DEFAULT_MODULES`。
  - 具体改法：删除 L104 `modules_data = _DEFAULT_MODULES`，在 try 块内成功时赋值 `modules_data = candidate`，except 时 raise。

  **Must NOT do**: 不删除 `_DEFAULT_MODULES` 常量定义（可能有测试引用）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 8
  - **Blocked By**: None

  **References**:
  - `pipeline/layers/aplus_generator.py:100-119` — Gemini 调用和 fallback 逻辑

  **Acceptance Criteria**:
  - [ ] except 块中不再有 `pass`，改为 `raise`

  **QA Scenarios**:

  ```
  Scenario: 无静默 pass
    Tool: Bash
    Steps:
      1. grep -A1 "except Exception" pipeline/layers/aplus_generator.py | grep -c "pass"
    Expected Result: 0
    Evidence: .sisyphus/evidence/task-3-no-pass.txt
  ```

  **Commit**: YES (group)

- [ ] 4. delivery.py — version 创建失败 raise

  **What to do**:
  - **L305-310**: `except Exception: pass` → `except Exception: log.warning("create_version failed for project %s", project_id, exc_info=True)` 或直接 raise。
  - 老板决策是「数据完整性 → raise」，所以改为：移除 try/except，让 `create_version()` 的异常直接传播。或保留 try 但 except 中 raise。

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 8
  - **Blocked By**: None

  **References**:
  - `pipeline/layers/delivery.py:305-310` — try/except 包裹 create_version

  **Acceptance Criteria**:
  - [ ] `create_version` 调用失败时异常不被吞掉

  **QA Scenarios**:

  ```
  Scenario: 无 pass 在 delivery create_version
    Tool: Bash
    Steps:
      1. grep -A1 "except Exception" pipeline/layers/delivery.py | grep -c "pass"
    Expected Result: 0
    Evidence: .sisyphus/evidence/task-4-no-pass.txt
  ```

  **Commit**: YES (group)

- [ ] 5. tag_system.py — AI 标签生成失败 log.warning

  **What to do**:
  - **L149-150**: `except Exception: pass` → `except Exception: log.warning("AI scene tag generation failed", exc_info=True)`
  - 仍然 `return []`（标签是 optional enrichment，不应阻断流水线）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 8
  - **Blocked By**: None

  **References**:
  - `pipeline/layers/tag_system.py:144-151` — AI 标签生成 except 块
  - 检查文件顶部 logger 变量名

  **Acceptance Criteria**:
  - [ ] except 块有 `log.warning` 调用

  **QA Scenarios**:

  ```
  Scenario: warning 日志已添加
    Tool: Bash
    Steps:
      1. grep -A2 "except Exception" pipeline/layers/tag_system.py | grep -c "warning"
    Expected Result: ≥ 1
    Evidence: .sisyphus/evidence/task-5-warning.txt
  ```

  **Commit**: YES (group)

- [ ] 6. slot_planner.py — KB 查询失败 log.warning

  **What to do**:
  - **L92-93**: `except Exception: pass` → `except Exception: log.warning("KB popular entries query failed, skipping", exc_info=True)`

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 8
  - **Blocked By**: None

  **References**:
  - `pipeline/layers/slot_planner.py:87-93`

  **Acceptance Criteria**:
  - [ ] except 块有 `log.warning`

  **Commit**: YES (group)

- [ ] 7. qa_gate.py — 图片尺寸读取失败 log.warning

  **What to do**:
  - **L669-670**: `except Exception: pass` → `except Exception: log.warning("Failed to read image dimensions for %s", image_path, exc_info=True)`
  - 仍然让 width/height 保持 None（尺寸读取是 optional）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 8
  - **Blocked By**: None

  **References**:
  - `pipeline/layers/qa_gate.py:664-670`

  **Acceptance Criteria**:
  - [ ] except 块有 `log.warning`

  **Commit**: YES (group)

- [ ] 8. 更新所有受影响测试

  **What to do**:
  - **test_amazon_data.py**: 原来测试 mock fallback 行为的用例 → 改为验证 `KeepaDataError` 被 raise
  - **test_brief_generator 相关**: 如果有测试 `_DEFAULT_BRIEF` fallback 的 → 改为验证 Gemini 失败时 raise
  - **test_aplus_generator 相关**: 同理
  - **test_delivery 相关**: 如果有测试 version 创建静默失败的 → 改为验证 raise
  - 搜索所有引用 `_mock_reviews`, `_mock_qa`, `_DEFAULT_BRIEF`, `_DEFAULT_MODULES` 的测试文件
  - 运行完整测试 suite 确认 ≥ 631 passed

  **Must NOT do**: 不删除与 mock_adapter.py / mock_engine.py 相关的测试

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2 (sequential after Wave 1)
  - **Blocks**: Task 9
  - **Blocked By**: Tasks 1-7

  **References**:
  - `tests/test_amazon_data.py` — mock fallback 测试
  - 运行 `grep -rl "_mock_reviews\|_mock_qa\|_DEFAULT_BRIEF\|_DEFAULT_MODULES" tests/` 找所有受影响测试

  **Acceptance Criteria**:
  - [ ] 全量测试 ≥ 631 passed, 0 failed

  **QA Scenarios**:

  ```
  Scenario: 全量测试通过
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py
    Expected Result: ≥ 631 passed, 0 failed
    Evidence: .sisyphus/evidence/task-8-test-results.txt
  ```

  **Commit**: YES
  - Message: `test(pipeline): update tests for exception-raise behavior`

---

## Final Verification Wave

- [ ] F1. 运行全量测试确认 ≥ 631 passed
- [ ] F2. grep 确认无残留 `except Exception:\n\s+pass` 在修改过的 7 个文件中
- [ ] F3. 手动确认 orchestrator.py 未被修改

---

## Commit Strategy

- **Single commit** for all source changes (Tasks 1-7): `fix(pipeline): remove silent exception swallowing and mock fallbacks`
- **Second commit** for test updates (Task 8): `test(pipeline): update tests for exception-raise behavior`

---

## Success Criteria

### Verification Commands

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py
# Expected: ≥ 631 passed, 0 failed

grep -rn "except Exception" pipeline/layers/amazon_data.py pipeline/layers/brief_generator.py pipeline/layers/aplus_generator.py pipeline/layers/delivery.py pipeline/layers/tag_system.py pipeline/layers/slot_planner.py pipeline/layers/qa_gate.py | grep -A1 "pass"
# Expected: 0 matches (no silent pass remaining in modified files)
```

### Final Checklist

- [ ] All mock fallback removed from amazon_data.py
- [ ] Gemini failures in brief_generator + aplus_generator raise exceptions
- [ ] Optional enrichment failures log.warning (not silent pass)
- [ ] delivery.py version creation failure raises
- [ ] All tests ≥ 631 passed
- [ ] orchestrator.py unchanged
