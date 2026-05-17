# Issues / Gotchas

## 2026-04-19
- PromptAsset, DeliveryVersion 是已有表，新增列必须走 ALTER TABLE
- TrendForecast 是全新表，create_all() 可直接处理
- 置信度路由阈值与现有 _QA_PASS_THRESHOLD=70 不同（70 是旧通过线，新路由用 80/50），注意不冲突
