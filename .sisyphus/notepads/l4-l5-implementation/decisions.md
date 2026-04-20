# Decisions

## 2026-04-19
- 不用 Alembic，用 create_all() + 手写 ALTER TABLE（幂等）
- 匿名化单向不可逆，不建反查表
- A/B 公式: performance_score = 0.6*CTR + 0.4*CVR, 阈值 >=0.75
- 趋势引擎用纯 Python statistics 模块（不引入 numpy/scipy）
- 飞轮默认关闭，env var 显式开启
- TrendForecast 新表: create_all() 自动处理，不需要 ALTER TABLE
