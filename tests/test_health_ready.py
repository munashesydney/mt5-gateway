"""Readiness reflects MT5 availability only; the kill switch is reported, not a fault."""

from types import SimpleNamespace

import pytest
from flask import Flask

import routes.health as health_route
from kill_switch import KillSwitch


class _Connection:
    def __init__(self, connected, auth_failed=False):
        self._connected = connected
        self._auth_failed = auth_failed

    def is_connected(self):
        return self._connected

    def get_status(self):
        return SimpleNamespace(value="connected" if self._connected else "disconnected")

    def get_last_error(self):
        return None if self._connected else "terminal down"

    def is_auth_failed(self):
        return self._auth_failed


@pytest.fixture
def make_client(monkeypatch, tmp_path):
    def _make(connected=True, kill_engaged=False, auth_failed=False):
        connection = _Connection(connected, auth_failed)
        monkeypatch.setattr(
            health_route.MT5Connection,
            "get_instance",
            classmethod(lambda cls: connection),
        )
        monkeypatch.setattr(
            health_route.mt5, "terminal_info", lambda: SimpleNamespace(), raising=False
        )
        monkeypatch.setattr(
            health_route.mt5, "account_info", lambda: SimpleNamespace(), raising=False
        )
        switch = KillSwitch(tmp_path / "kill-switch")
        if kill_engaged:
            switch.engage()
        monkeypatch.setattr(health_route, "kill_switch", switch)
        app = Flask(__name__)
        app.register_blueprint(health_route.health_bp)
        return app.test_client()

    return _make


def test_ready_when_connected_and_kill_switch_released(make_client):
    response = make_client(connected=True, kill_engaged=False).get("/health/ready")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ready",
        "mt5_status": "connected",
        "kill_switch_active": False,
    }


def test_ready_stays_200_while_kill_switch_is_engaged(make_client):
    """An engaged kill switch is a trading gate the gateway keeps serving through
    (reads, flatten, release), so it must not flip readiness: compose
    `service_healthy` dependants could not restart during a weekend kill."""
    response = make_client(connected=True, kill_engaged=True).get("/health/ready")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ready"
    assert body["kill_switch_active"] is True


def test_not_ready_when_mt5_is_disconnected(make_client):
    response = make_client(connected=False, kill_engaged=False).get("/health/ready")

    assert response.status_code == 503
    body = response.get_json()
    assert body["status"] == "not_ready"
    assert body["mt5_status"] == "disconnected"
    assert body["error"] == "terminal down"
    assert body["auth_failed"] is False
    assert body["kill_switch_active"] is False


def test_not_ready_reports_auth_failure(make_client):
    """A broker-rejected login is permanent until credentials change, so the
    readiness payload flags it for callers (plane) to park the tenant instead
    of restarting the container forever."""
    response = make_client(connected=False, auth_failed=True).get("/health/ready")

    assert response.status_code == 503
    body = response.get_json()
    assert body["status"] == "not_ready"
    assert body["auth_failed"] is True


def test_health_reports_the_server_time_offset(make_client, monkeypatch):
    from time_utils import derive_from_tick, set_derived_offset

    set_derived_offset(None)
    now = 1_785_000_000
    derive_from_tick("BTCUSDm", now + 1, utc_now=now)
    monkeypatch.setattr("time_utils.time.time", lambda: now + 30)

    body = make_client(connected=True).get("/health").get_json()

    assert body["server_time"]["offset_seconds"] == 0
    assert body["server_time"]["source"] == "derived"
    assert body["server_time"]["symbol"] == "BTCUSDm"
    assert body["server_time"]["age_seconds"] == 30
    set_derived_offset(None)
