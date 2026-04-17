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
    templates_dir: str = field(
        default_factory=lambda: os.getenv("AIP_TEMPLATES_DIR", "templates")
    )
    output_dir: str = field(
        default_factory=lambda: os.getenv("AIP_OUTPUT_DIR", "data/output")
    )
    image_output_dir: str = field(
        default_factory=lambda: os.getenv("AIP_IMAGE_OUTPUT_DIR", "data/images")
    )
    log_level: str = field(default_factory=lambda: os.getenv("AIP_LOG_LEVEL", "INFO"))
    flask_port: int = field(
        default_factory=lambda: int(os.getenv("AIP_FLASK_PORT", "5100"))
    )


config = Config()
