import time
from types import SimpleNamespace

import pytest
from flask import Flask, jsonify

from mt5_connection import MT5Connection, mt5
from routes.pool import install_pool_guard, pool_bp
from security import install_security_hooks


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MT5_POOL_MODE", "1")
    monkeypatch.setenv("API_KEY", "private")
    app = Flask(__name__)
    install_security_hooks(app)
    install_pool_guard(app)
    app.register_blueprint(pool_bp)
    app.add_url_rule(
        "/account", view_func=lambda: jsonify(login=mt5.account_info().login)
    )
    monkeypatch.setattr(mt5, "initialize", lambda **kw: True, raising=False)
    monkeypatch.setattr(mt5, "login", lambda **kw: True, raising=False)
    monkeypatch.setattr(
        mt5,
        "account_info",
        lambda: SimpleNamespace(login=1, server="broker"),
        raising=False,
    )
    monkeypatch.setattr(mt5, "shutdown", lambda: None, raising=False)
    conn = MT5Connection()
    monkeypatch.setattr(MT5Connection, "_instance", conn)
    monkeypatch.setattr(conn, "_refresh_server_offset", lambda: None)
    return app.test_client()


def execute(client, **changes):
    data = dict(
        login="1",
        server="broker",
        password="not-real",
        method="GET",
        path="/account",
        deadline=time.time() + 10,
    )
    data.update(changes)
    return client.post(
        "/internal/execute", json=data, headers={"Authorization": "Bearer private"}
    )


def test_auth_required(client):
    assert client.post("/internal/execute", json={}).status_code == 401


def test_raw_account_endpoint_is_blocked(client):
    assert (
        client.get("/account", headers={"Authorization": "Bearer private"}).status_code
        == 403
    )


def test_correct_account_is_dispatched_and_credentials_are_cleared(client):
    response = execute(client)
    assert response.status_code == 200 and response.json["login"] == 1
    assert MT5Connection.get_instance()._pool_credentials is None
    assert not MT5Connection.get_instance().is_connected()


def test_wrong_account_and_expired_requests_never_dispatch(client, monkeypatch):
    assert execute(client, login="2").status_code == 503
    assert execute(client, deadline=time.time() - 1).status_code == 503


def test_arbitrary_paths_are_not_dispatched(client):
    assert execute(client, path="/kill/release", method="POST").status_code == 400
    assert execute(client, path="/internal/execute", method="POST").status_code == 400


def test_deadline_and_account_are_checked_at_submission_boundary():
    from mt5_connection import SerializedMT5, pool_execution

    calls = []
    module = SimpleNamespace(
        account_info=lambda: SimpleNamespace(login=1, server="broker"),
        order_send=lambda body: calls.append(body),
    )
    ipc = SerializedMT5(module)
    token = pool_execution.set((1, "broker", time.time() - 1))
    try:
        with pytest.raises(RuntimeError, match="deadline"):
            ipc.order_send({})
    finally:
        pool_execution.reset(token)
    token = pool_execution.set((2, "broker", time.time() + 10))
    try:
        with pytest.raises(RuntimeError, match="identity"):
            ipc.order_send({})
    finally:
        pool_execution.reset(token)
    assert calls == []


def test_pool_readiness_waits_for_boot_authorization(monkeypatch, tmp_path):
    import autologin
    from routes.health import health_bp

    monkeypatch.setenv("MT5_POOL_MODE", "1")
    marker = tmp_path / "authorized"
    monkeypatch.setenv("MT5_LOGIN_SERVER_FILE", str(marker))
    monkeypatch.setattr(autologin, "wine_path", lambda path, nt: path)
    app = Flask(__name__)
    app.register_blueprint(health_bp)
    client = app.test_client()
    assert client.get("/health/ready").status_code == 503
    marker.write_text("broker-address")
    assert client.get("/health/ready").json["pool_worker"] is True


def test_shutdown_failure_does_not_leave_execution_lock_held(client, monkeypatch):
    import threading

    from routes.pool import execution_lock

    def fail_shutdown():
        raise RuntimeError("cleanup failed")

    monkeypatch.setattr(mt5, "shutdown", fail_shutdown)
    assert execute(client).status_code == 500
    acquired = []

    def probe():
        held = execution_lock.acquire(blocking=False)
        acquired.append(held)
        if held:
            execution_lock.release()

    thread = threading.Thread(target=probe)
    thread.start()
    thread.join()
    assert acquired == [True]
