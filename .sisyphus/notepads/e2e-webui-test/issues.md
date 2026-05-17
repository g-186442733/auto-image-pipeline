# Web UI E2E Test — Issues Found

> Date: 2026-04-20

## 🔴 Critical

### 1. LLM QA 全部 fallback — 无真实质检

- **位置**: QA Dashboard (`/qa-dashboard`)
- **现象**: 115 条检查全部是 `llm_qa` 类型，所有详情都是 `"LLM evaluation unavailable — fallback evaluation"`
- **影响**: QA 步骤形同虚设，所有图片自动 PASS（fallback score=75）或 FAIL（score=0），无真实 LLM 评估
- **日志**: `WARNING aip.qa_gate: LLM QA evaluation failed (empty response); returning fallback pass (score=75)`
- **根因推测**: QA 调用的 LLM API 返回空响应，可能是 API key 未配置或模型端点不可用

### 2. Report / Deliver 路由不存在 (404)

- **位置**: `/project/9/report`, `/project/9/deliver`
- **现象**: 返回 404
- **影响**: Pipeline 完成后无法查看报告或交付页面，E2E 流程断裂
- **根因**: `app.py` 中未定义 report/deliver 路由

## 🟡 Medium

### 3. 竞品基准数据为空值

- **位置**: Benchmarks (`/benchmarks`)
- **现象**: benchmark 表列出了 ASIN 和 slot_index，但评分、分析列均为 "—"
- **影响**: 竞品分析结果未填充到 benchmark 表，用户无法对比竞品图片质量

### 4. 状态显示中英文混用

- **位置**: 项目详情页 (`/project/9`)
- **现象**: 创建后显示"草稿"（中文），完成后显示 "completed"（英文）
- **影响**: UI 一致性差

### 5. 复核页面项目名重复

- **位置**: Review (`/review`)
- **现象**: 4 条复核记录中有 3 条都是 "JLab Go Air Pop TWS Earbuds"，摘要都是 "first delivery"
- **影响**: 可能是每次 pipeline 运行都创建新的复核记录，未去重

## 🟢 Low

### 6. 知识库页面为空

- **位置**: Knowledge (`/knowledge`)
- **现象**: 页面可访问但无内容
- **影响**: 知识库功能尚未实现或无数据

### 7. Port 5000 被 macOS AirTunes 占用

- **现象**: 默认端口 5000 返回 403（AirTunes/925.5.1）
- **影响**: 必须手动改用 5001，`__main__.py` 的 `web` 命令默认绑 5000 会失败
