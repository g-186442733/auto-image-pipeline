# ADR-006: Amazon 数据源选用 Keepa API

## Status
Accepted

## Date
2026-04-17

## Context

项目需要采集 Amazon 竞品产品数据，包括：
- BSR（Best Seller Rank）及品类排名
- 价格走势（历史最低价、当前价）
- 评分与评论数量
- 历史趋势数据

数据采集方式主要有三类：官方 API、第三方 SaaS、自行爬虫。Amazon 官方 MWS/SP-API 对数据访问限制较多，不适合竞品分析场景。

## Decision

Amazon 数据源选用 **Keepa API**（订阅费 $19/月）。

通过 Keepa Python 客户端库调用，按 ASIN 批量查询产品数据，结果存入 SQLite。

注意：Keepa API **不包含产品主图**。主图 URL 需通过其他方式获取（如 Amazon 产品页面解析或 Amazon PA-API）。

## Consequences

### Positive
- 合法合规：官方授权 API，不存在封号或法律风险
- 历史数据完整：Keepa 保存多年的价格和 BSR 历史，爬虫无法获取
- 零维护：无需维护反爬策略，无需处理验证码、IP 封禁
- Python 客户端库成熟，接入简单

### Negative
- 不含产品主图，需要另外解决主图获取问题
- 月费 $19，长期使用有固定成本
- Token 配额制（每次查询消耗 Token，月度有上限），批量查询需控制节奏

## Alternatives Considered

| 方案 | 优点 | 缺点 | 未选原因 |
|------|------|------|----------|
| Playwright 爬虫 | 免费，可获取主图 | 违反 Amazon ToS，高封禁风险，维护成本高 | 法律风险和维护成本不可接受 |
| Jungle Scout API | 功能更全，含关键词数据 | $49/月，超出预算；数据聚焦于卖家工具，不如 Keepa 的历史趋势完整 | 成本过高 |
