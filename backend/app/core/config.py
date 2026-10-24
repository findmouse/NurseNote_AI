"""アプリケーション設定（環境変数から読み込む）"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    app_name: str = "NurseNote AI"
    api_prefix: str = "/api/v1"
    debug: bool = True

    # DB
    database_url: str = (
        "postgresql+asyncpg://nursenote:nursenote_pass@db:5432/nursenote"
    )

    # 認証
    jwt_secret: str = "dev-secret-change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12  # 12 時間

    # 開発用シードデータ
    seed_on_startup: bool = True
    seed_password: str = "nurse1234"

    # 記録の保持・表示のデフォルト
    default_recent_days: int = 7

    # LLM。既定は院内 Ollama。クラウドは明示許可かつ API キーがあるときだけ。
    # キーはここへ書かず、環境変数 DEEPSEEK_API_KEY / QWEN_API_KEY で渡す。
    llm_provider: str = "ollama"  # ollama / deepseek / qwen
    allow_cloud_llm: bool = False
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen3:8b"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"


settings = Settings()
