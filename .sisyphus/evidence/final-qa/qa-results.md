# F3: Real Manual QA — 功能验收测试结果

**日期**: 2026-04-20
**测试环境**: macOS, Python 3.14, SQLite

## 测试结果

```
Scenario 1 /review: PASS
Scenario 2 /qa-dashboard: PASS
Scenario 3 BrandProfile.guidelines: PASS
Scenario 4 promote_to_knowledge: PASS
Scenario 5 aip web --help: PASS
Scenario 6 Approve 操作: PASS
Scenarios: [6/6 pass]
VERDICT: APPROVE
```

## 测试细节

### Scenario 1: /review 路由

- **结果**: PASS — `create_app()` 创建 Flask app，GET /review 返回 200，内容包含 review 关键字
- **注意**: 原始脚本用 `from pipeline.web.app import app`，实际导出为 `create_app` 工厂函数

### Scenario 2: /qa-dashboard 路由

- **结果**: PASS — GET /qa-dashboard 返回 200，内容包含 qa/dashboard 关键字

### Scenario 3: BrandProfile.guidelines 字段落库

- **结果**: PASS — 字段存在，写入 "F3 QA test content" 后读回一致

### Scenario 4: promote_to_knowledge 端到端

- **结果**: PASS — 创建 PromptAsset（含必填字段 slot_index=0），调用 promote_to_knowledge 成功返回 KnowledgeEntry
- **注意**: PromptAsset 有 NOT NULL 约束 `slot_index`，原始脚本 MagicMock 无法落库

### Scenario 5: aip web --help

- **结果**: PASS — 输出包含 `--port INTEGER` 和 `--debug` 选项

### Scenario 6: Approve 操作

- **结果**: PASS — POST /review/{id}/approve 返回 302 重定向，`client_signed_at` 被设置为非空时间戳
- **注意**: DeliveryVersion 无 `status`/`version` 字段，使用 `version_number` 和 `client_signed_at` 作为审批标志
