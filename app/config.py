from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": an unrecognised key in .env must never stop the app from starting.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./trustvault.db"
    storage_dir: str = "./storage"
    max_upload_mb: int = 20
    session_ttl_minutes: int = 60
    secret_key: str = "dev-only-change-me"
    cookie_secure: bool = False
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    # First administrator, created at startup if no such user exists (set both; use a strong password).
    admin_email: str = ""
    admin_password: str = ""
    admin_name: str = "Administrator"
    # Extra comma-separated emails that may enter the Administrator portal with Google.
    admin_emails: str = ""
    # Google sign-in (Google Identity Services). Create an OAuth Web client ID in Google Cloud Console.
    google_client_id: str = ""
    # Owner uploads must be approved by an administrator before anyone else can see them.
    require_document_approval: bool = True
    # Optional email notifications (any SMTP provider). Leave smtp_host empty to disable.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    public_url: str = "http://localhost:8000"
    # Per-IP limits (per process)
    register_per_hour: int = 10
    login_per_5min: int = 40
    # Demo data is for development only (python scripts/seed.py --demo)
    seed_demo: bool = False
    seed_password: str = ""
    # AI sharing suggestions. 'rules' needs no key. 'anthropic' re-ranks the rule-based shortlist.
    ai_provider: str = "rules"
    anthropic_api_key: str = ""
    ai_model: str = "claude-haiku-5-5"
    suggestion_ttl_hours: int = 24
    suggestions_per_hour: int = 20


settings = Settings()
