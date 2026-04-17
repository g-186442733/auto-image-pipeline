# ADR-002: AI 出图使用抽象层（Adapter Pattern）

## Status
Accepted

## Date
2026-04-17

## Context

项目核心功能之一是 AI 图片生成。当前市场上主流的图片生成模型包括 Flux、Midjourney、ComfyUI（本地）、DALL-E 等，各有优劣，且价格、质量、风格适合程度会随时间变化。

如果直接将代码绑定到某个具体模型的 API，未来切换成本极高，LoRA 微调等扩展能力也难以接入。

## Decision

AI 出图模块采用**抽象层设计（Adapter Pattern）**，对上层代码暴露统一接口，底层具体实现可随时替换。

接口约定：
```
generate_image(prompt: str, style_params: dict) -> ImageResult
```

L2 阶段先用 Mock 实现通过接口验证，之后再接入真实模型（Flux / MJ / ComfyUI）。

## Consequences

### Positive
- 可随时切换底层模型，无需修改上层业务逻辑
- 未来接入 LoRA 微调模型，只需新增一个 Adapter 实现
- Mock 先行，允许在真实 API 可用之前完成全流程开发和测试
- 多模型 A/B 对比测试变得简单

### Negative
- 初期多一层抽象，代码量略多
- 接口设计需要提前考虑不同模型的参数差异，可能产生过度设计
- Mock 实现和真实实现之间的行为差距需要额外测试覆盖

## Alternatives Considered

| 方案 | 优点 | 缺点 | 未选原因 |
|------|------|------|----------|
| 直接绑定 Flux API | 代码简单直接 | 切换模型需大规模重构 | 锁定单一供应商，灵活性差 |
| 直接绑定 Midjourney | 图片质量有优势 | API 不稳定，且同样锁定单一供应商 | 同上，且 MJ API 为非官方，风险更高 |
