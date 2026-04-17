# 接口契约文档

> **项目**：Auto Image Pipeline — 跨境电商自动化主图生产系统  
> **版本**：L2 MVP  
> **更新**：2026-04-17  
> **状态**：Wave 0 接口定义（实现在 Wave 2-4）

---

## 总览

本文档定义系统各模块的**公开接口**——函数签名、参数/返回类型、核心数据结构、错误码。所有 Wave 2-4 的实现代码必须与本文档保持一致；如需变更，先更新本文档再改代码。

模块按五层架构组织（参见 `docs/architecture.md`）：

| 层         | 模块              | 入口                                 |
| ---------- | ----------------- | ------------------------------------ |
| 客户输入层 | `input_layer`     | `pipeline/layers/input_layer.py`     |
| 分析决策层 | `amazon_data`     | `pipeline/layers/amazon_data.py`     |
| 分析决策层 | `vision_analyzer` | `pipeline/layers/vision_analyzer.py` |
| 分析决策层 | `prompt_manager`  | `pipeline/layers/prompt_manager.py`  |
| 出图生产层 | `prompt_engine`   | `pipeline/layers/prompt_engine.py`   |
| 出图生产层 | `slot_planner`    | `pipeline/layers/slot_planner.py`    |
| 出图生产层 | `adapters`        | `pipeline/adapters/base.py`          |
| 质检交付层 | `qa_gate`         | `pipeline/layers/qa_gate.py`         |
| 数据回流层 | `feedback_loop`   | `pipeline/layers/feedback_loop.py`   |
| 编排入口   | CLI               | `pipeline/__main__.py`               |
| 编排入口   | Flask Web         | `pipeline/web/app.py`                |

---

## 核心数据结构

以下 6 个数据结构贯穿各层接口，对应 `pipeline/models/` 下的 SQLAlchemy ORM 模型。

### ProjectBrief

客户输入的项目信息，对应 `Project` 模型。

```python
# pipeline/models/project.py
class Project(Base):
    id: int               # PK, auto-increment
    name: str             # 项目名称, max 200
    asin: str             # 目标 ASIN, max 20, indexed
    category: str         # 品类, max 100
    status: str           # draft | analyzing | generating | qa | done | failed
    notes: str            # 备注 (Text)
    created_at: datetime
    updated_at: datetime
```

**Status 状态机**：`draft → analyzing → generating → qa → done`（任意步骤可 → `failed`）

### CompetitorAnalysis

竞品分析结果，对应 `AmazonBenchmark` 模型。

```python
# pipeline/models/benchmark.py
class AmazonBenchmark(Base):
    id: int
    project_id: int       # FK → projects.id
    competitor_asin: str   # 竞品 ASIN, max 20
    slot_index: int        # 图片槽位 1-8
    image_url: str         # 图片 URL, max 1000
    analysis: str          # Vision 分析结果 JSON (Text)
    score: float           # 综合评分 0-100
    created_at: datetime
```

### SlotPlan

套图规划，对应 `SlotPlan` 模型。

```python
# pipeline/models/slot_plan.py
class SlotPlan(Base):
    id: int
    project_id: int       # FK → projects.id
    slot_index: int        # 槽位 1-8 (MAIN, ALT1-ALT6, VIDEO_THUMB)
    intent_tag: str        # 意图标签 e.g. INT_HERO
    layout_tag: str        # 布局标签
    style_tag: str         # 风格标签
    color_tag: str         # 色彩标签
    description: str       # 槽位描述 (Text)
    created_at: datetime
```

### PromptPackage

Prompt 资产，对应 `PromptAsset` 模型。

```python
# pipeline/models/prompt_asset.py
class PromptAsset(Base):
    id: int
    project_id: int       # FK → projects.id
    slot_index: int        # 槽位 1-8
    prompt_text: str       # 完整正向 prompt (Text, NOT NULL)
    negative_prompt: str   # 负面 prompt (Text)
    model_name: str        # AI 模型名 e.g. "flux-1.1-pro"
    version: int           # 版本号, default 1
    image_path: str        # 生成图片路径, max 500
    created_at: datetime
```

### GeneratedImage / QAReport

质检记录，对应 `QARecord` 模型。

```python
# pipeline/models/qa_record.py
class QARecord(Base):
    id: int
    prompt_asset_id: int   # FK → prompt_assets.id
    check_type: str        # resolution | aspect_ratio | background | text_overlay | compliance
    passed: int            # 0=fail, 1=pass
    score: float           # 检查得分 0-100
    details: str           # 详细信息 JSON (Text)
    created_at: datetime
```

### ABTest (数据回流)

A/B 测试记录，对应 `ABTest` 模型。

```python
# pipeline/models/ab_test.py
class ABTest(Base):
    id: int
    project_id: int        # FK → projects.id
    slot_index: int
    variant_a_id: int      # FK → prompt_assets.id
    variant_b_id: int      # FK → prompt_assets.id
    winner: str            # "A" | "B" | None
    metric: str            # CTR | CVR | session_rate
    score_a: float
    score_b: float
    notes: str
    created_at: datetime
```

---

## 模块接口

### input_layer — 客户输入层

```python
def create_project(brief: dict) -> Project:
    """创建新项目。

    Args:
        brief: 项目信息字典，必需字段:
            - name (str): 项目名称
            - asin (str): 目标 ASIN
            - category (str): 品类
            可选字段:
            - notes (str): 备注

    Returns:
        Project: 新建的项目 ORM 实例 (status="draft")

    Raises:
        E_INPUT_001: brief 缺少必需字段 (name/asin/category)
        E_INPUT_002: ASIN 格式校验失败 (非 B0 开头或长度不对)
    """

def upsert_brand_profile(data: dict) -> BrandProfile:
    """创建或更新品牌画像。

    Args:
        data: 品牌信息字典，必需字段:
            - project_id (int): 关联项目 ID
            - brand_name (str): 品牌名称
            可选字段:
            - color_palette (str): JSON 色板 e.g. '["#FF6B35","#004E89"]'
            - font_family (str): 字体族
            - tone (str): 品牌调性 e.g. "premium", "playful"
            - logo_path (str): logo 文件路径
            - guidelines (str): 品牌指南文本

    Returns:
        BrandProfile: 品牌画像 ORM 实例

    Raises:
        E_INPUT_003: project_id 对应的项目不存在
    """
```

### amazon_data — Amazon 数据采集

```python
def fetch_category_top(category: str, market: str = "US", top_n: int = 20) -> list[AmazonBenchmark]:
    """采集品类 Top N 竞品基准数据。

    通过 Keepa API 获取品类 BSR 排名，抓取 listing 主图。

    Args:
        category: Amazon 品类节点名或 ID
        market: 市场站点代码 (US/UK/DE/JP)
        top_n: 采集前 N 名, 默认 20, 上限 50

    Returns:
        list[AmazonBenchmark]: 竞品基准记录列表

    Raises:
        E_AMAZON_001: Keepa API key 未配置或无效
        E_AMAZON_002: 品类未找到
        E_AMAZON_003: API 调用频率超限 (429)
    """

def fetch_asin_detail(asin: str) -> dict:
    """获取单个 ASIN 的详细信息。

    Returns:
        dict: 包含 title, price, bsr_rank, review_count, rating, category_path

    Raises:
        E_AMAZON_004: ASIN 不存在或已下架
    """

def scrape_listing_images(asin: str) -> list[str]:
    """抓取 listing 全部图片 URL。

    Returns:
        list[str]: 图片 URL 列表 (最多 9 张)

    Raises:
        E_AMAZON_004: ASIN 不存在或已下架
    """
```

### vision_analyzer — 竞品图片分析

```python
def analyze_image(image_url: str) -> dict:
    """使用 GPT-4o Vision 分析单张图片。

    Returns:
        dict: 分析结果，包含:
            - intent_tag (str): 推断的意图标签
            - role_tags (list[str]): 识别的角色标签
            - composition (str): 构图描述
            - color_palette (list[str]): 主色提取
            - text_detected (bool): 是否包含文字
            - quality_score (float): 质量评分 0-100

    Raises:
        E_VISION_001: OpenAI API key 未配置
        E_VISION_002: 图片 URL 无法访问 (404/403)
        E_VISION_003: API 调用失败 (5xx / timeout)
    """

def analyze_competitor_listing(asin: str) -> list[dict]:
    """分析竞品 listing 全部图片。

    内部调用 scrape_listing_images + analyze_image。

    Returns:
        list[dict]: 每张图片的分析结果 (同 analyze_image 返回格式)
    """
```

### prompt_manager — Prompt 资产管理

```python
def create_prompt_asset(
    project_id: int,
    slot_index: int,
    prompt_text: str,
    negative_prompt: str = "",
    model_name: str = "flux-1.1-pro",
) -> PromptAsset:
    """创建新的 Prompt 资产。

    Raises:
        E_PROMPT_001: project_id 不存在
        E_PROMPT_002: slot_index 超出范围 (不在 1-8)
    """

def update_prompt_asset(asset_id: int, **kwargs) -> PromptAsset:
    """更新现有 Prompt 资产，自动递增 version。

    可更新字段: prompt_text, negative_prompt, model_name

    Raises:
        E_PROMPT_003: asset_id 不存在
    """

def get_prompt_asset(id_or_name: int | str, version: int | None = None) -> PromptAsset:
    """获取 Prompt 资产。

    Args:
        id_or_name: 按 ID (int) 或项目名 (str) 查询
        version: 指定版本号, None 则取最新版

    Raises:
        E_PROMPT_003: 资产不存在
    """

def list_prompt_assets(category: str | None = None) -> list[PromptAsset]:
    """列出 Prompt 资产。

    Args:
        category: 按品类筛选, None 返回全部
    """

def seed_default_templates() -> int:
    """初始化默认 Prompt 模板。

    从 config.templates_dir 读取 JSON 模板文件，批量写入数据库。

    Returns:
        int: 成功导入的模板数量
    """
```

### prompt_engine — Prompt 组装引擎

```python
def assemble_prompt(
    prompt_asset_id: int,
    variables: dict,
    brand_profile: BrandProfile | None = None,
) -> str:
    """组装最终 prompt。

    将 PromptAsset.prompt_text 中的 {variable_slots} 替换为实际值，
    追加品牌约束（如有），拼接 negative_prompt。

    六维变量骨架 (variables dict keys):
        - composition: 构图指令
        - subject: 主体描述
        - environment: 环境/背景
        - camera: 镜头语言 (angle, focal_length, DOF)
        - tone: 调性/色调
        - constraints: 额外约束条件

    Returns:
        str: 完整的 prompt 字符串

    Raises:
        E_PROMPT_003: prompt_asset_id 不存在
        E_ENGINE_001: variables 缺少必需 key
    """

def generate_slot_prompts(project_id: int) -> dict[str, str]:
    """为项目的全部槽位批量生成 prompt。

    根据 SlotPlan 为每个槽位组装 prompt，返回 slot_index → prompt 映射。

    Returns:
        dict[str, str]: key 为 "MAIN"/"ALT1"/... , value 为组装后的 prompt

    Raises:
        E_ENGINE_002: 项目无 SlotPlan (需先调用 slot_planner)
    """
```

### slot_planner — 套图规划器

```python
def generate_slot_plan(project_id: int) -> list[SlotPlan]:
    """为项目生成 8 槽位套图规划。

    基于竞品分析结果 (AmazonBenchmark) + 品牌画像 (BrandProfile) + 标签体系，
    为 8 个槽位分配意图标签、布局/风格/色彩标签。

    槽位映射 (pipeline/constants/tags.py SLOT_MAPPING):
        1: MAIN — hero shot, white background
        2: ALT1 — secondary angle or lifestyle
        3: ALT2 — infographic with feature callouts
        4: ALT3 — detail / close-up
        5: ALT4 — comparison or size reference
        6: ALT5 — packaging / what-in-box
        7: ALT6 — lifestyle or model shot
        8: VIDEO_THUMB — video thumbnail

    Returns:
        list[SlotPlan]: 8 个 SlotPlan ORM 实例

    Raises:
        E_PLANNER_001: 项目无竞品分析数据 (需先跑 amazon_data + vision_analyzer)
    """
```

### adapters — AI 出图适配器

```python
# pipeline/adapters/base.py
from dataclasses import dataclass
from enum import Enum

class JobStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class ImageResult:
    job_id: str
    status: JobStatus
    image_url: str | None = None
    image_path: str | None = None
    error: str | None = None
    metadata: dict | None = None

class BaseImageAdapter:
    """AI 出图适配器抽象基类 (ADR-002)。

    所有具体适配器 (Flux/MJ/ComfyUI) 必须继承此类。
    """

    def generate(self, prompt: str, params: dict | None = None) -> ImageResult:
        """提交出图任务。

        Args:
            prompt: 完整 prompt 文本
            params: 模型特定参数 (e.g. width, height, steps, guidance_scale)

        Returns:
            ImageResult: 包含 job_id 和初始 status

        Raises:
            E_ADAPTER_001: 适配器未配置 (缺少 API key)
            E_ADAPTER_002: 参数校验失败
        """
        raise NotImplementedError

    def check_status(self, job_id: str) -> JobStatus:
        """查询任务状态。

        Raises:
            E_ADAPTER_003: job_id 不存在
        """
        raise NotImplementedError

    def download_image(self, job_id: str, dest_path: str) -> str:
        """下载生成的图片到本地。

        Returns:
            str: 本地文件路径

        Raises:
            E_ADAPTER_003: job_id 不存在
            E_ADAPTER_004: 任务尚未完成
        """
        raise NotImplementedError
```

### qa_gate — 质检门

```python
def run_qa_checks(slot_plan_id: int) -> list[QARecord]:
    """对指定槽位执行全部质检项。

    检查项: resolution, aspect_ratio, background, text_overlay, compliance

    Returns:
        list[QARecord]: 每项检查的结果记录

    Raises:
        E_QA_001: slot_plan_id 无对应的已生成图片
    """

def check_resolution(image_path: str) -> bool:
    """检查图片分辨率是否满足 Amazon 要求 (≥1600px 长边)。"""

def check_aspect_ratio(image_path: str, expected: str = "1:1") -> bool:
    """检查图片宽高比。

    Args:
        expected: 期望比例字符串, 默认 "1:1", 支持 "1:1.2" 等
    """

def check_background(image_path: str) -> float:
    """检测主图白底占比。

    Returns:
        float: 白色像素占比 0.0-1.0 (MAIN 槽位要求 ≥ 0.85)
    """

def check_text_overlay(image_path: str) -> bool:
    """检测图片是否包含文字覆盖 (MAIN 槽位禁止)。

    Returns:
        bool: True = 检测到文字
    """
```

### feedback_loop — 数据回流

```python
def record_ab_test(
    project_id: int,
    slot_index: int,
    variant_a_id: int,
    variant_b_id: int,
    winner: str | None = None,
    metric: str = "CTR",
    score_a: float | None = None,
    score_b: float | None = None,
    notes: str = "",
) -> ABTest:
    """记录 A/B 测试结果。

    Raises:
        E_FEEDBACK_001: variant_a_id 或 variant_b_id 不存在
    """

def record_delivery_result(
    project_id: int,
    slot_index: int,
    result: dict,
) -> None:
    """记录交付结果 (客户反馈/上架效果)。

    Args:
        result: 包含 accepted (bool), feedback (str), metrics (dict) 等
    """

def get_category_insights(category: str) -> dict:
    """获取品类洞察。

    聚合该品类下所有项目的 A/B 测试数据和 QA 通过率。

    Returns:
        dict: 包含:
            - avg_qa_pass_rate (float)
            - top_intent_tags (list[str]): 最常用的意图标签
            - ab_win_patterns (list[dict]): A/B 测试胜出模式
            - project_count (int)
    """

def export_project_report(project_id: int) -> dict:
    """导出项目全量报告。

    Returns:
        dict: 包含项目信息、品牌画像、竞品分析、SlotPlan、
              Prompt 资产、QA 结果、A/B 测试汇总

    Raises:
        E_FEEDBACK_002: project_id 不存在
    """
```

### CLI — 命令行编排

```
pipeline init       # 交互式创建项目 (→ input_layer.create_project)
pipeline analyze    # 采集竞品 + Vision 分析 (→ amazon_data + vision_analyzer)
pipeline plan       # 生成套图规划 (→ slot_planner.generate_slot_plan)
pipeline generate   # AI 出图 (→ adapters.generate)
pipeline qa         # 质检 (→ qa_gate.run_qa_checks)
pipeline run        # 全流程: init → analyze → plan → generate → qa
pipeline report     # 导出项目报告 (→ feedback_loop.export_project_report)
```

所有子命令通过 `argparse` 注册，共享 `--project-id` 和 `--verbose` 参数。

### Flask Web — Web UI 端点

```
GET  /                    # Dashboard: 项目列表
GET  /project/<id>        # 项目详情页 (含进度状态机)
POST /project/new         # 创建新项目 (JSON body → input_layer.create_project)
GET  /prompts             # Prompt 资产浏览/管理
GET  /benchmarks          # 竞品基准数据浏览
POST /project/<id>/run    # 触发全流程执行
GET  /project/<id>/report # 项目报告 (JSON)
```

---

## 错误码一览

| 错误码           | 模块            | 描述                                         |
| ---------------- | --------------- | -------------------------------------------- |
| `E_INPUT_001`    | input_layer     | 项目 brief 缺少必需字段 (name/asin/category) |
| `E_INPUT_002`    | input_layer     | ASIN 格式校验失败                            |
| `E_INPUT_003`    | input_layer     | project_id 对应的项目不存在                  |
| `E_AMAZON_001`   | amazon_data     | Keepa API key 未配置或无效                   |
| `E_AMAZON_002`   | amazon_data     | 品类未找到                                   |
| `E_AMAZON_003`   | amazon_data     | API 调用频率超限 (429)                       |
| `E_AMAZON_004`   | amazon_data     | ASIN 不存在或已下架                          |
| `E_VISION_001`   | vision_analyzer | OpenAI API key 未配置                        |
| `E_VISION_002`   | vision_analyzer | 图片 URL 无法访问                            |
| `E_VISION_003`   | vision_analyzer | Vision API 调用失败                          |
| `E_PROMPT_001`   | prompt_manager  | project_id 不存在                            |
| `E_PROMPT_002`   | prompt_manager  | slot_index 超出范围 (1-8)                    |
| `E_PROMPT_003`   | prompt_manager  | Prompt 资产不存在                            |
| `E_ENGINE_001`   | prompt_engine   | variables 缺少必需 key                       |
| `E_ENGINE_002`   | prompt_engine   | 项目无 SlotPlan                              |
| `E_PLANNER_001`  | slot_planner    | 项目无竞品分析数据                           |
| `E_ADAPTER_001`  | adapters        | 适配器未配置                                 |
| `E_ADAPTER_002`  | adapters        | 参数校验失败                                 |
| `E_ADAPTER_003`  | adapters        | job_id 不存在                                |
| `E_ADAPTER_004`  | adapters        | 任务尚未完成                                 |
| `E_QA_001`       | qa_gate         | 无对应的已生成图片                           |
| `E_FEEDBACK_001` | feedback_loop   | A/B variant_id 不存在                        |
| `E_FEEDBACK_002` | feedback_loop   | project_id 不存在                            |

---

## 辅助类型

### BrandProfile

品牌画像，对应 `BrandProfile` 模型（见 `pipeline/models/brand.py`）。

```python
class BrandProfile(Base):
    id: int
    project_id: int       # FK → projects.id
    brand_name: str       # 品牌名称, max 200
    color_palette: str    # JSON 色板
    font_family: str      # 字体族
    tone: str             # 品牌调性
    logo_path: str        # logo 路径
    guidelines: str       # 品牌指南
    created_at: datetime
```

### TagAssignment

标签分配记录（参见 `pipeline/models/tag_assignment.py`），将标签与 SlotPlan 或 AmazonBenchmark 关联。

### Config

全局配置 (参见 `pipeline/config.py`)，通过环境变量 + `.env` 文件加载。

```python
@dataclass
class Config:
    db_path: str            # AIP_DB_PATH, default "data/pipeline.db"
    db_url: str             # AIP_DB_URL, default "sqlite:///data/pipeline.db"
    keepa_api_key: str      # KEEPA_API_KEY
    openai_api_key: str     # OPENAI_API_KEY
    openai_base_url: str    # OPENAI_BASE_URL
    openai_model: str       # AIP_OPENAI_MODEL, default "gpt-4o"
    templates_dir: str      # AIP_TEMPLATES_DIR, default "templates"
    output_dir: str         # AIP_OUTPUT_DIR, default "data/output"
    image_output_dir: str   # AIP_IMAGE_OUTPUT_DIR, default "data/images"
    log_level: str          # AIP_LOG_LEVEL, default "INFO"
    flask_port: int         # AIP_FLASK_PORT, default 5100
```
