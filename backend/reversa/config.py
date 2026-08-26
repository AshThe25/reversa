"""Settings. Defaults are picked so `uvicorn reversa.main:app` just works with
no .env — Razorpay and Anthropic both fall back to offline instead of blowing up,
because whoever clones this repo won't have my keys.
"""

from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

IST = ZoneInfo("Asia/Kolkata")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="REFLOW_", extra="ignore"
    )

    database_url: str = "sqlite:///./reversa.db"

    # --- Razorpay -----------------------------------------------------------
    # Test-mode keys. Absent keys put the client in `offline` mode, where it
    # serves recorded fixtures instead of calling the API.
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_base_url: str = "https://api.razorpay.com/v1"

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

    @property
    def has_razorpay(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret)

    @property
    def has_llm(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
