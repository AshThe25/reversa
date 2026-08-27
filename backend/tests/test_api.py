"""API surface: auth, scopes, validation, headers, limits.

These run against the seeded demo database rather than a fixture, because the
things worth testing here - a 403 on execute, a CSP header on an error response -
only exist once the whole app is assembled.
"""

import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from reversa.config import get_settings
from reversa.main import create_app
from reversa.security.auth import OPERATOR, issue


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(scope="module")
def demo_headers(client):
    token = client.post("/api/auth/session").json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def operator_headers():
    settings = get_settings()
    token, _ = issue("test-operator", OPERATOR, settings.session_secret)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def hero(client, demo_headers):
    incidents = client.get("/api/incidents", headers=demo_headers).json()["incidents"]
    assert incidents, "seeded world produced no incidents - run scripts.seed_world"
    return max(incidents, key=lambda i: i["revenue_exposed_paise"])


# --- auth -------------------------------------------------------------------

def test_health_needs_no_auth(client):
    assert client.get("/api/health").status_code == 200


def test_protected_routes_reject_anonymous_callers(client):
    for path in ("/api/overview", "/api/incidents", "/api/audit"):
        assert client.get(path).status_code == 401


def test_rejection_does_not_say_why(client):
    """Telling a caller whether the signature or the expiry failed hands them an
    oracle to work against."""
    body = client.get(
        "/api/overview", headers={"Authorization": "Bearer v1.abc.def"}
    ).json()
    assert body["detail"] == {"error": "unauthenticated"}


def test_a_tampered_token_is_rejected(client, demo_headers):
    bad = demo_headers["Authorization"][:-6] + "aaaaaa"
    assert client.get("/api/overview", headers={"Authorization": bad}).status_code == 401


def test_demo_session_can_read_and_simulate(client, demo_headers):
    assert client.get("/api/overview", headers=demo_headers).status_code == 200


def test_demo_session_cannot_move_money(client, demo_headers, hero):
    """The core of the demo's safety story: an evaluator can explore every future
    in the wind tunnel and has no path to committing one."""
    r = client.post("/api/experiments/execute",
                    json={"incident_id": hero["id"]}, headers=demo_headers)
    assert r.status_code == 403
    assert r.json()["detail"]["required"] == "execute"


def test_operator_session_can_execute(client, operator_headers, hero):
    r = client.post("/api/experiments/execute",
                    json={"incident_id": hero["id"], "scenario": "optimal"},
                    headers=operator_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["arms"]["holdout"]["payments"] > 0


# --- headers ----------------------------------------------------------------

def test_security_headers_are_on_every_response(client, demo_headers):
    for path, headers in (("/api/health", {}), ("/api/overview", demo_headers)):
        r = client.get(path, headers=headers)
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


def test_csp_forbids_inline_script(client):
    csp = client.get("/api/health").headers["Content-Security-Policy"]
    assert "'unsafe-eval'" not in csp
    assert "script-src 'self'" in csp


def test_security_headers_survive_an_error_response(client):
    """The paths that skip the middleware are the ones an attacker looks for."""
    r = client.get("/api/overview")
    assert r.status_code == 401
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_every_response_carries_a_request_id(client):
    assert len(client.get("/api/health").headers["X-Request-Id"]) == 16


# --- validation -------------------------------------------------------------

def test_unknown_incident_is_404_not_500(client, demo_headers):
    r = client.post("/api/windtunnel",
                    json={"incident_id": "inc_does_not_exist"}, headers=demo_headers)
    assert r.status_code == 404


def test_capacity_override_rejects_unknown_actions(client, demo_headers, hero):
    r = client.post("/api/windtunnel",
                    json={"incident_id": hero["id"],
                          "capacity": {"mind_control": 5}},
                    headers=demo_headers)
    assert r.status_code == 422


def test_capacity_override_rejects_absurd_limits(client, demo_headers, hero):
    """An unbounded capacity lets a caller ask for a billion-variable LP."""
    r = client.post("/api/windtunnel",
                    json={"incident_id": hero["id"],
                          "capacity": {"payment_link": 10**9}},
                    headers=demo_headers)
    assert r.status_code == 422


def test_holdout_fraction_is_bounded(client, operator_headers, hero):
    r = client.post("/api/experiments/execute",
                    json={"incident_id": hero["id"], "holdout_fraction": 0.99},
                    headers=operator_headers)
    assert r.status_code == 422


def test_holdout_plus_exploration_must_leave_a_treatment_arm(client,
                                                             operator_headers, hero):
    r = client.post("/api/experiments/execute",
                    json={"incident_id": hero["id"],
                          "holdout_fraction": 0.8, "exploration_fraction": 0.25},
                    headers=operator_headers)
    assert r.status_code == 422


def test_unknown_scenario_lists_what_is_available(client, operator_headers, hero):
    r = client.post("/api/experiments/execute",
                    json={"incident_id": hero["id"], "scenario": "wishful_thinking"},
                    headers=operator_headers)
    assert r.status_code == 422
    assert "optimal" in r.json()["detail"]["available"]


# --- content ----------------------------------------------------------------

def test_system_route_declares_which_mode_each_adapter_is_in(client, demo_headers):
    body = client.get("/api/system", headers=demo_headers).json()
    mode = body["adapters"]["razorpay"]["mode"]
    assert mode in ("RAZORPAY TEST MODE", "SIMULATION MODE")
    assert body["adapters"]["razorpay"]["payment_link_budget"]["limit"] <= 30


def test_wind_tunnel_returns_every_branch_with_the_same_baseline(client,
                                                                 demo_headers, hero):
    body = client.post("/api/windtunnel",
                       json={"incident_id": hero["id"]}, headers=demo_headers).json()
    keys = {s["key"] for s in body["scenarios"]}
    assert {"do_nothing", "retry_now", "optimal"} <= keys
    assert len({s["natural_recovery_paise"] for s in body["scenarios"]}) == 1


def test_cohort_separates_exposure_from_what_arrives_anyway(client, demo_headers, hero):
    body = client.get(f"/api/incidents/{hero['id']}/cohort", headers=demo_headers).json()
    assert body["addressable_paise"] == (
        body["revenue_exposed_paise"] - body["natural_recovery_paise"]
    )
    assert body["natural_recovery_paise"] > 0


def test_audit_chain_verifies_over_the_api(client, demo_headers):
    body = client.get("/api/audit/verify", headers=demo_headers).json()
    assert body["valid"] is True


def test_audit_events_expose_the_hash_chain(client, demo_headers):
    events = client.get("/api/audit?limit=5", headers=demo_headers).json()["events"]
    assert events
    for e in events:
        assert e["prev_hash"] and e["entry_hash"] and e["actor"]


# --- configuration ----------------------------------------------------------

def test_env_prefix_matches_the_documented_one():
    """Regression, and a nasty one.

    The project was renamed early and a case-sensitive find/replace missed the
    uppercase env_prefix, so it stayed REFLOW_ while every doc, .env.example and
    README table said REVERSA_. Nothing failed loudly - keys, secrets and access
    codes were simply never read and the app ran on defaults forever. The
    operator login silently degraded to a guest session, which is exactly the
    class of bug that only surfaces in front of someone.
    """
    from reversa.config import Settings

    assert Settings.model_config["env_prefix"] == "REVERSA_"


def test_documented_variables_actually_bind(monkeypatch):
    from reversa.config import Settings

    monkeypatch.setenv("REVERSA_DEMO_ACCESS_CODE", "unit-test-code")
    monkeypatch.setenv("REVERSA_ANTHROPIC_API_KEY", "sk-ant-unit-test")
    settings = Settings(_env_file=None)
    assert settings.demo_access_code == "unit-test-code"
    assert settings.has_llm


def test_a_live_razorpay_key_is_refused(monkeypatch):
    """Everything here assumes test mode. A live key would let a demo dunning
    run fire real payment links at real customers, and there is no override."""
    import pytest as _pytest

    from reversa.config import Settings

    with _pytest.raises(Exception, match="live Razorpay key"):
        Settings(razorpay_key_id="rzp_live_ABC123", _env_file=None)
