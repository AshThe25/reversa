"""Request and response shapes.

Pydantic on the way in is the input-validation layer - anything not described
here does not reach a handler. Bounds are tight on purpose: `holdout_fraction`
is capped below 0.9 because a 95% holdout is not an experiment, it is an
outage, and an unbounded `capacity` lets a caller ask the optimiser for a
billion-variable linear program.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from reversa.models import ActionType

MAX_CAPACITY_PER_ACTION = 100_000


class SessionRequest(BaseModel):
    access_code: str | None = Field(default=None, max_length=128)


class ScanRequest(BaseModel):
    force: bool = False


class CapacityOverride(BaseModel):
    capacity: dict[str, int] | None = None

    @field_validator("capacity")
    @classmethod
    def _sane(cls, v: dict[str, int] | None) -> dict[str, int] | None:
        if v is None:
            return v
        allowed = {a.value for a in ActionType}
        for action, limit in v.items():
            if action not in allowed:
                raise ValueError(f"unknown action {action!r}")
            if not 0 <= limit <= MAX_CAPACITY_PER_ACTION:
                raise ValueError(
                    f"capacity for {action} must be between 0 and {MAX_CAPACITY_PER_ACTION}"
                )
        return v


class WindTunnelRequest(CapacityOverride):
    incident_id: str = Field(min_length=4, max_length=64)


class ExecuteRequest(CapacityOverride):
    incident_id: str = Field(min_length=4, max_length=64)
    scenario: str = Field(default="optimal", max_length=40)
    holdout_fraction: float = Field(default=0.15, ge=0.0, lt=0.9)
    exploration_fraction: float = Field(default=0.05, ge=0.0, le=0.3)

    @field_validator("exploration_fraction")
    @classmethod
    def _leaves_a_treatment_arm(cls, v: float, info) -> float:
        holdout = info.data.get("holdout_fraction", 0.0)
        if holdout + v >= 0.95:
            raise ValueError(
                "holdout plus exploration would leave almost no treatment arm"
            )
        return v


class PolicyCompileRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4_000)
    name: str = Field(default="Merchant policy", max_length=80)


class ChaosRequest(BaseModel):
    incident_id: str = Field(min_length=4, max_length=64)
    volume_multiplier: float = Field(default=1.0, ge=0.1, le=20.0)
    capacity_multiplier: float = Field(default=1.0, ge=0.0, le=5.0)
    arrivals_per_minute: float = Field(default=60.0, ge=1.0, le=10_000.0)
