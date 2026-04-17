# ADR-005: 竞品图片分析选用 Gemini 2.5 Flash Vision

## Status

Accepted (supersedes original GPT-4o Vision decision)

## Date

2026-04-17 (updated 2026-04-18)

## Context

项目需要对 Amazon 竞品主图进行自动化分析，提取以下信息：

- 构图方式（主体位置、留白比例）
- 色调风格（主色调、冷暖倾向）
- 使用场景（户外/室内/纯白背景等）
- 视觉标签（对应三层标签体系中的视觉特征标签）

分析结果将作为提示词生成的输入，直接影响最终图片质量。

原方案选用 GPT-4o Vision（直连 OpenAI），但项目统一接入 147AI 作为 API 供应商后，改用 Gemini 2.5 Flash 的 Vision 能力。

## Decision

竞品图片分析选用 **Gemini 2.5 Flash**（通过 147AI `/v1/chat/completions`）。

图片以 base64 `image_url` 方式嵌入 messages，返回文本分析结果。实现见 `pipeline/adapters/gemini_vision_adapter.py`。

## Consequences

### Positive

- 统一供应商：与出图（gpt-image-1）和编辑（gemini-2.5-flash-image-preview）共用 147AI，一个 API Key
- 成本更低：Gemini Flash 价格显著低于 GPT-4o Vision
- 速度快：Flash 系列针对低延迟优化
- 视觉理解能力足够满足竞品分析需求

### Negative

- 结构化输出不如 GPT-4o 稳定，需要 prompt 强约束 JSON 格式
- 依赖 147AI 中转
- Gemini 偶尔对细粒度色彩描述不够精确

## Alternatives Considered

| 方案                        | 优点                         | 缺点                         | 未选原因                   |
| --------------------------- | ---------------------------- | ---------------------------- | -------------------------- |
| GPT-4o Vision (OpenAI 直连) | 分析精度最高，结构化输出稳定 | 需单独 OpenAI Key，$0.005/张 | 供应商不统一               |
| GPT-4o Vision (147AI 中转)  | 精度高，统一供应商           | 成本仍高于 Gemini Flash      | 成本优先，Flash 精度已够用 |
| 本地 Qwen2-VL-72B           | 零 API 成本，数据不出境      | 需要 80G+ VRAM GPU           | 硬件条件限制               |
