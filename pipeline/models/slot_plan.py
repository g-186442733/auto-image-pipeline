from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    func,
)
from pipeline.models.base import Base
from pipeline.models.pipeline_run import PipelineRun  # noqa: F401 — 确保 pipeline_runs 表先创建


class SlotPlan(Base):
    __tablename__ = "slot_plans"
    # 唯一约束：同一 project + slot_index + pipeline_run 只能有一条；保留多 run 版本历史
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "slot_index",
            "pipeline_run_id",
            name="uq_slot_plan_project_slot_run",
        ),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    slot_index = Column(Integer, nullable=False)
    intent_tag = Column(String(30))
    layout_tag = Column(String(30))
    style_tag = Column(String(30))
    color_tag = Column(String(30))
    description = Column(Text)
    # ── 蒸馏自竞品视觉分析的策略字段 ──
    visual_focus = Column(Text)  # 图片应视觉呈现什么
    key_message = Column(Text)  # 核心卖点一句话
    competitor_contrast = Column(Text)  # 相比竞品的视觉差异化方向
    lighting_tag = Column(String(50))  # 光源类型
    angle_tag = Column(String(30))  # 拍摄角度
    dof_tag = Column(String(30))  # 景深
    background_tag = Column(String(50))  # 背景材质/类型
    overlay_text = Column(Text)  # 图片叠加文字内容
    shot_type = Column(String(50))  # 镜头类型（全身/半身/特写/微距等）
    subject_material = Column(Text)  # 主体材质描述
    gen_params = Column(
        String(200)
    )  # 出图参数：MJ用 --ar --stylize，DALL-E/Gemini用自然语言
    # ── 新增字段 ──
    title = Column(String(100))  # 前端展示用的槽位标题，如"主图-白底正面"
    negative_prompt = Column(Text)  # Slot 层面的负向提示词，比 PromptAsset 更上游
    comparison_structure = Column(
        String(200)
    )  # 对比图结构，如 "left=competitor,right=product"
    # ── LLM 推理链（slot_planner 输出的 chain-of-thought，用于 regen 回注）──
    reasoning = Column(Text)  # LLM 解释选择这些 tag 的推理过程，regen 时作为上下文注入
    # ── Per-slot 自定义字段（用户在规划确认阶段填写）──
    custom_prompt = Column(Text)  # 追加到 STEP 3 生成 prompt 末尾
    custom_image_paths = Column(Text)  # 逗号分隔，最多 2 张，STEP 4 追加给 Gemini
    # ── 生成后回写的视觉特征（vision_analyzer 分析结果）──
    generated_lighting = Column(String(50))
    generated_angle = Column(String(30))
    generated_shot_type = Column(String(50))
    generated_bg_material = Column(String(50))
    generated_color_temp = Column(String(30))
    generated_saturation = Column(String(20))
    created_at = Column(DateTime, server_default=func.now())
    tenant_id = Column(Integer, nullable=True, index=True)
    # 关联到当次 pipeline_run，用于版本历史
    pipeline_run_id = Column(
        Integer, ForeignKey("pipeline_runs.id"), nullable=True, index=True
    )
