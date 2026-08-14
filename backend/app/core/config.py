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


settings = Settings()
