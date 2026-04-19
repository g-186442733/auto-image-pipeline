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
        default_factory=lambda: os.getenv("AIP_DB_URL", "sqlite:///data/pipeline.db")
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
        default_factory=lambda: os.getenv("AIP_IMAGE_MODEL", "gpt-image-1")
    )
    edit_model: str = field(
        default_factory=lambda: os.getenv(
            "AIP_EDIT_MODEL", "gemini-2.5-flash-image-preview"
        )
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
    parallel_analyze: bool = field(
        default_factory=lambda: (
            os.getenv("AIP_PARALLEL_ANALYZE", "1").lower() in ("1", "true", "yes")
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


config = Config()
