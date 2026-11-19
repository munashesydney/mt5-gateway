"""Private pooled execution: authentication, login and dispatch share one lock."""

import math
import os
import re
import time
from threading import RLock

from flask import Blueprint, current_app, g, jsonify, request

from mt5_connection import ConnectionStatus, MT5Connection, mt5, pool_execution

pool_bp = Blueprint("pool", __name__)
execution_lock = RLock()
READS = {
    "/account",
    "/orders",
    "/get_positions",
    "/health/ready",
    "/history_deals_range",
}
WRITES = {"/order", "/close_position", "/close_all_positions", "/modify_sl_tp"}


def install_pool_guard(app):
    @app.before_request
    def guard():
        if os.getenv("MT5_POOL_MODE") != "1":
            return
        if request.path.startswith("/health/") or request.path == "/internal/execute":
            return
        if not getattr(g, "pool_dispatch", False):
            return jsonify(
                error="Pooled workers require private execution",
                error_type="validation_error",
            ), 403


@pool_bp.post("/internal/execute")
def execute():
    if os.getenv("MT5_POOL_MODE") != "1" or not os.getenv("API_KEY"):
        return jsonify(error="Pooled execution is disabled"), 403
    data = request.get_json(silent=True) or {}
    try:
        login = int(data["login"])
        server, password = data["server"], data["password"]
        method, path = data["method"], data["path"]
        deadline = float(data["deadline"])
        if not all(isinstance(v, str) and v for v in (server, password, method, path)):
            raise ValueError()
        allowed = (
            (method == "GET" and path.split("?")[0] in READS)
            or (method == "POST" and path in WRITES)
            or (method in {"PUT", "DELETE"} and re.fullmatch(r"/orders/\d+", path))
        )
        if not allowed or not math.isfinite(deadline):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        return jsonify(
            error="Invalid pooled operation", error_type="validation_error"
        ), 400

    remaining = min(20.0, deadline - time.time())
    if remaining <= 0 or not execution_lock.acquire(timeout=remaining):
        return jsonify(
            error="Execution deadline expired",
            error_type="capacity_error",
            submitted=False,
        ), 503
    conn = MT5Connection.get_instance()
    context_token = pool_execution.set((login, server, deadline))
    try:
        if time.time() >= deadline:
            return jsonify(
                error="Execution deadline expired",
                error_type="capacity_error",
                submitted=False,
            ), 503
        credentials = {"login": login, "password": password, "server": server}
        conn._pool_credentials = credentials
        conn._auth_failed = False
        conn._set_status(ConnectionStatus.DISCONNECTED)
        timeout = max(1, int(min(15, deadline - time.time()) * 1000))
        if not mt5.initialize(**credentials, timeout=timeout) or not mt5.login(
            **credentials, timeout=timeout
        ):
            return jsonify(
                error="Broker login failed",
                error_type="connection_error",
                submitted=False,
            ), 503
        account = mt5.account_info()
        if account is None or account.login != login or account.server != server:
            return jsonify(
                error="Broker account identity mismatch",
                error_type="connection_error",
                submitted=False,
            ), 503
        from lib import reset_symbol_cache
        from time_utils import set_derived_offset

        reset_symbol_cache()
        set_derived_offset(None)
        conn._set_status(ConnectionStatus.CONNECTED)
        conn._refresh_server_offset()
        # Login and offset discovery may have consumed the entire deadline.
        if time.time() >= deadline:
            return jsonify(
                error="Execution deadline expired",
                error_type="capacity_error",
                submitted=False,
            ), 503
        # Reuse existing validation, kill switch, response formats and handlers.
        headers = {"Authorization": request.headers.get("Authorization", "")}
        with current_app.test_request_context(
            path, method=method, json=data.get("body"), headers=headers
        ):
            g.pool_dispatch = True
            return current_app.full_dispatch_request()
    finally:
        pool_execution.reset(context_token)
        conn._pool_credentials = None
        conn._set_status(ConnectionStatus.DISCONNECTED)
        try:
            mt5.shutdown()
        finally:
            execution_lock.release()
