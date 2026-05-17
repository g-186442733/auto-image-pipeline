# Architecture Decision Records (ADR)

本目录记录 `auto-image-pipeline` 项目的架构决策。每条 ADR 描述一个重要的技术或架构选择，包括背景、决策内容、后果与备选方案。

## ADR 列表

| 编号 | 标题 | 状态 | 日期 |
|------|------|------|------|
| [ADR-001](./ADR-001-maturity-level-l2.md) | MVP 起步成熟度选择 L2 | ✅ Accepted | 2026-04-17 |
| [ADR-002](./ADR-002-ai-abstraction-layer.md) | AI 出图使用抽象层（Adapter Pattern） | ✅ Accepted | 2026-04-17 |
| [ADR-003](./ADR-003-sqlite-database.md) | 数据库选择 SQLite | ✅ Accepted | 2026-04-17 |
| [ADR-004](./ADR-004-python-orchestration.md) | 纯 Python 脚本编排，不使用工作流引擎 | ✅ Accepted | 2026-04-17 |
| [ADR-005](./ADR-005-gpt4o-vision-analysis.md) | 竞品图片分析选用 GPT-4o Vision | ✅ Accepted | 2026-04-17 |
| [ADR-006](./ADR-006-keepa-api-data-source.md) | Amazon 数据源选用 Keepa API | ✅ Accepted | 2026-04-17 |
| [ADR-007](./ADR-007-three-label-taxonomy.md) | 三层标签体系设计 | ✅ Accepted | 2026-04-17 |

## 关于 ADR

ADR（Architecture Decision Record）是一种轻量级文档实践，用于记录具有重要影响的架构决策。每条记录回答三个问题：

- **为什么**要做这个决策（Context）
- **做了什么**决策（Decision）
- **产生了什么**影响（Consequences）

## 状态说明

| 状态 | 含义 |
|------|------|
| Proposed | 提案中，待讨论 |
| Accepted | 已接受，当前执行 |
| Deprecated | 已弃用，被新决策取代 |
| Superseded | 被特定 ADR 取代 |
