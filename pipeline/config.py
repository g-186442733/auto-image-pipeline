import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    db_path: str = field(
        default_factory=lambda: os.getenv("AIP_DB_PATH", "data/pipeline.db")
    )
    db_url: str = field(
        default_factory=lambda: os.getenv("AIP_DB_URL", "postgresql://localhost/aip_db")
    )
    keepa_api_key: str = field(default_factory=lambda: os.getenv("KEEPA_API_KEY", ""))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_base_url: str = field(
        default_factory=lambda: os.getenv(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        )
    )
    openai_model: str = field(
        default_factory=lambda: os.getenv("AIP_OPENAI_MODEL", "gpt-4o")
    )
    # 147AI provider credentials
    api_key: str = field(default_factory=lambda: os.getenv("AIP_API_KEY", ""))
    api_base_url: str = field(
        default_factory=lambda: os.getenv("AIP_API_BASE_URL", "https://147ai.com/v1")
    )
    image_model: str = field(
        default_factory=lambda: os.getenv("AIP_IMAGE_MODEL", "gpt-image-2-client")
    )
    edit_model: str = field(
        default_factory=lambda: os.getenv("AIP_EDIT_MODEL", "gpt-image-2-client")
    )
    fallback_model: str = field(
        default_factory=lambda: os.getenv("AIP_FALLBACK_MODEL", "gpt-image-2")
    )
    vision_model: str = field(
        default_factory=lambda: os.getenv("AIP_VISION_MODEL", "gemini-2.5-flash")
    )
    templates_dir: str = field(
        default_factory=lambda: os.getenv("AIP_TEMPLATES_DIR", "templates")
    )
    output_dir: str = field(
        default_factory=lambda: os.getenv("AIP_OUTPUT_DIR", "data/output")
    )
    image_output_dir: str = field(
        default_factory=lambda: os.getenv("AIP_IMAGE_OUTPUT_DIR", "data/images")
    )
    image_output_size: int = field(
        default_factory=lambda: int(os.getenv("AIP_IMAGE_OUTPUT_SIZE", "2000"))
    )
    parallel_analyze: bool = field(
        default_factory=lambda: (
            os.getenv("AIP_PARALLEL_ANALYZE", "1").lower() in ("1", "true", "yes")
        )
    )
    vision_provider: str = field(
        default_factory=lambda: os.getenv("VISION_PROVIDER", "openai")
    )
    http_proxy: str = field(
        default_factory=lambda: (
            os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or ""
        )
    )
    log_level: str = field(default_factory=lambda: os.getenv("AIP_LOG_LEVEL", "INFO"))
    flask_port: int = field(
        default_factory=lambda: int(os.getenv("AIP_FLASK_PORT", "5100"))
    )
    # 飞轮配置（默认关闭）
    flywheel_enabled: bool = field(
        default_factory=lambda: (
            os.getenv("AIP_FLYWHEEL_ENABLED", "false").lower() == "true"
        )
    )
    flywheel_auto_deliver: bool = field(
        default_factory=lambda: (
            os.getenv("AIP_FLYWHEEL_AUTO_DELIVER", "false").lower() == "true"
        )
    )
    flywheel_confidence_threshold: float = field(
        default_factory=lambda: float(
            os.getenv("AIP_FLYWHEEL_CONFIDENCE_THRESHOLD", "85")
        )
    )

    @property
    def image_adapter(self) -> str:
        m = self.image_model.lower()
        # gemini 系列 或 -client 封装（如 gpt-image-2-client）均走 chat completions
        if "gemini" in m or m.endswith("-client"):
            return "gemini_image"
        if "gpt" in m or "dall-e" in m:
            return "gpt_image"
        return "mock"

    @property
    def edit_adapter(self) -> str:
        m = self.edit_model.lower()
        # -client 封装模型走 chat completions（gemini_image_adapter）
        # 标准 gpt-image / dall-e 走 /images/edits multipart（gpt_image_adapter）
        if "gemini" in m or m.endswith("-client"):
            return "gemini_image"
        if "gpt" in m or "dall-e" in m:
            return "gpt_image"
        return "mock"


config = Config()
