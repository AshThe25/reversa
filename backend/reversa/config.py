"""Settings. Defaults are picked so `uvicorn reversa.main:app` just works with
no .env — Razorpay and Anthropic both fall back to offline instead of blowing up,
because whoever clones this repo won't have my keys.
"""

from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

IST = ZoneInfo("Asia/Kolkata")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # REVERSA_, not REFLOW_. The project was renamed early and a
        # case-sensitive find/replace missed this one uppercase string, so for
        # most of the build every documented environment variable was silently
        # ignored - keys, secrets, access codes, all of it. Nothing failed
        # loudly; the app just quietly ran with defaults forever.
        env_file=".env", env_prefix="REVERSA_", extra="ignore"
    )

    database_url: str = "sqlite:///./reversa.db"

    # --- Razorpay -----------------------------------------------------------
    # Test-mode keys. Absent keys put the client in `offline` mode, where it
    # serves recorded fixtures instead of calling the API.
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_base_url: str = "https://api.razorpay.com/v1"
    razorpay_webhook_secret: str | None = None

    # --- sessions -----------------------------------------------------------
    # Generated per process when unset, which is right for a laptop and wrong
    # for more than one replica - every restart invalidates live sessions. Set
    # REVERSA_SESSION_SECRET in any real deployment.
    session_secret: str = ""
    session_ttl_seconds: int = 8 * 3600

    # Fit the estimator and scan the day on boot rather than on first request.
    warm_on_startup: bool = True

    # Walk-up access. When empty, anyone can open a demo session - which is the
    # point for a judge with a link. Demo sessions never carry EXECUTE scope, so
    # they can explore every future without committing one.
    demo_access_code: str = ""
    allow_demo_sessions: bool = True

    # Browser origins allowed to call the API. Not "*" - a wildcard with
    # credentials is how a dashboard gets driven from someone else's tab.
    cors_origins: list[str] = [
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:4173", "http://127.0.0.1:4173",
    ]

    # Network behaviour for the adapter. Razorpay rate-limits, and a batch
    # executor that gives up on the first 429 is useless.
    http_timeout_seconds: float = 15.0
    http_max_attempts: int = 4
    http_backoff_base_seconds: float = 0.4

    # Razorpay caps test-mode businesses at 30 live Payment Links. We budget
    # below that so a demo run can never wedge the account.
    payment_link_budget: int = 24

    # --- Anthropic ----------------------------------------------------------
    anthropic_api_key: str | None = None
    llm_model: str = "claude-sonnet-5"
    llm_max_tokens: int = 1200

    # --- Experiment design --------------------------------------------------
    # Holdout fraction. Assignment is deterministic (hash of case id + salt),
    # so a rerun of the same corpus reproduces the same arms exactly.
    holdout_fraction: float = 0.20
    assignment_salt: str = "reversa-v1"

    # --- Compliance bounds (RBI / TRAI). These are hard ceilings; the policy
    # engine may choose to be more conservative, never less. -----------------
    contact_window_start_hour: int = 8   # IST, inclusive
    contact_window_end_hour: int = 19    # IST, exclusive (7pm)
    max_contacts_per_case: int = 3
    max_contacts_per_payer_per_day: int = 2
    min_hours_between_contacts: int = 18
    max_retries_per_case: int = 4
    case_ttl_days: int = 14

    # --- Sentinel -----------------------------------------------------------
    sentinel_window_minutes: int = 15
    sentinel_baseline_hours: int = 24
    sentinel_min_volume: int = 20        # slices thinner than this are not tested
    sentinel_fdr_q: float = 0.05         # Benjamini-Hochberg target FDR

    # --- Costs (paise). Used for cost-per-recovery and false-positive cost. --
    cost_sms_paise: int = 25
    cost_whatsapp_paise: int = 85
    cost_email_paise: int = 3
    cost_voice_paise: int = 450
    cost_retry_paise: int = 0            # a gateway retry is free; it costs goodwill

    @field_validator("razorpay_key_id")
    @classmethod
    def _refuse_live_keys(cls, v: str | None) -> str | None:
        """Hard stop on production credentials.

        Reversa moves money. Everything in this repo - the world generator, the
        simulated payer responses, the executor - assumes test mode. Handing it a
        live key would let a demo dunning run fire real payment links at real
        customers. There is no flag to override this; if you want live mode you
        write a different deployment, deliberately.
        """
        if v and v.startswith("rzp_live"):
            raise ValueError(
                "refusing to start with a live Razorpay key. Reversa is test-mode "
                "only - use an rzp_test_ key."
            )
        return v

    @model_validator(mode="after")
    def _sane_holdout(self) -> "Settings":
        if not 0.0 <= self.holdout_fraction < 0.9:
            raise ValueError("holdout_fraction must be in [0, 0.9)")
        if self.contact_window_start_hour >= self.contact_window_end_hour:
            raise ValueError("contact window start must precede its end")
        return self

    @property
    def has_razorpay(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret)

    @property
    def has_llm(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    if not settings.session_secret:
        import secrets as _secrets
        object.__setattr__(settings, "session_secret", _secrets.token_urlsafe(48))
    return settings
