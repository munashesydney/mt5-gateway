from collections import namedtuple

import lib

Position = namedtuple("Position", "ticket type magic")
TimedPosition = namedtuple("TimedPosition", "ticket type magic time")
Account = namedtuple("Account", "margin")


class FakeModule:
    """Stand-in for the raw MetaTrader5 module used inside call_atomic."""

    def __init__(self, state):
        self._state = state

    def shutdown(self):
        self._state["attached"] = False

    def initialize(self):
        self._state["attached"] = True
        self._state["reattaches"] += 1
        return True

    def last_error(self):
        return (1, "ok")


def _patch_connection(monkeypatch, values, margin=0.0, orders=()):
    """Simulate a connection whose position snapshot is empty until re-attached."""
    state = {"attached": False, "reattaches": 0}

    def positions_get(**kwargs):
        if not state["attached"]:
            return ()
        return values if kwargs.get("group") == "*" else ()

    monkeypatch.setattr(lib.mt5, "positions_get", positions_get, raising=False)
    monkeypatch.setattr(lib.mt5, "positions_total", lambda: 0, raising=False)
    monkeypatch.setattr(lib.mt5, "account_info", lambda: Account(margin), raising=False)
    monkeypatch.setattr(lib.mt5, "orders_get", lambda **kw: orders, raising=False)
    monkeypatch.setattr(
        lib.mt5, "call_atomic", lambda op: op(FakeModule(state)), raising=False
    )
    monkeypatch.setattr(lib, "_last_reattach", -1e9)
    return state


def test_get_positions_uses_the_wildcard_group_query(monkeypatch):
    # The terminal-cache quirk: the unfiltered call reads a stale local cache
    # and reports nothing, while the wildcard group query returns the open
    # positions. Listing must go through the group query.
    values = (Position(9521884, 0, 7),)
    calls = []

    def positions_get(**kwargs):
        calls.append(kwargs)
        return values if kwargs.get("group") == "*" else ()

    monkeypatch.setattr(lib.mt5, "positions_get", positions_get, raising=False)
    monkeypatch.setattr(lib.mt5, "positions_total", lambda: 0, raising=False)

    positions_df = lib.get_positions()

    assert [row["ticket"] for row in positions_df.to_dict(orient="records")] == [
        9521884
    ]
    assert calls[0] == {"group": "*"}


def test_get_positions_publishes_utc_open_time(monkeypatch):
    # MT5 reports position time in broker-server time; list rows must carry
    # the true UTC instant so consumers can stamp it Z without drifting.
    monkeypatch.setenv("MT5_SERVER_UTC_OFFSET_SECONDS", "7200")
    monkeypatch.delenv("MT5_SERVER_TIME_ZONE", raising=False)
    values = (TimedPosition(1, 0, 7, 1_794_873_915),)
    monkeypatch.setattr(
        lib.mt5, "positions_get", lambda **kw: values, raising=False
    )
    monkeypatch.setattr(lib.mt5, "positions_total", lambda: 1, raising=False)

    rows = lib.get_positions().to_dict(orient="records")

    assert rows[0]["time"] == 1_794_873_915
    assert rows[0]["time_utc"] == "2026-11-16T22:05:15Z"


def test_get_position_by_ticket_filters_in_python(monkeypatch):
    values = (Position(1, 0, 7), Position(2, 1, 7))
    monkeypatch.setattr(lib.mt5, "positions_get", lambda **kw: values, raising=False)

    found = lib.get_position_by_ticket(2)

    assert found is not None
    assert found.ticket == 2
    assert lib.get_position_by_ticket(3) is None


def test_get_positions_falls_back_when_group_is_unsupported(monkeypatch):
    values = (Position(5, 0, 7),)

    def positions_get(**kwargs):
        if kwargs:
            raise TypeError("unexpected keyword argument 'group'")
        return values

    monkeypatch.setattr(lib.mt5, "positions_get", positions_get, raising=False)
    monkeypatch.setattr(lib.mt5, "positions_total", lambda: 1, raising=False)

    positions_df = lib.get_positions()

    assert [row["ticket"] for row in positions_df.to_dict(orient="records")] == [5]


def test_get_positions_reattaches_a_stale_connection(monkeypatch):
    # Signature of a connection attached mid-login: position list and total
    # are empty while the server-side account still carries margin.
    values = (Position(9521884, 0, 7),)
    state = _patch_connection(monkeypatch, values, margin=2.2)

    positions = lib.get_all_positions()

    assert [position.ticket for position in positions] == [9521884]
    assert state["reattaches"] == 1


def test_get_positions_does_not_reattach_when_genuinely_flat(monkeypatch):
    # No margin and no positions means there is nothing to heal.
    state = _patch_connection(monkeypatch, (), margin=0.0)

    positions = lib.get_all_positions()

    assert positions == ()
    assert state["reattaches"] == 0


def test_get_positions_does_not_reattach_for_pending_order_margin(monkeypatch):
    # Pending orders tie up margin; an empty position list is honest here.
    values = (Position(3, 0, 7),)
    state = _patch_connection(monkeypatch, values, margin=2.2, orders=(object(),))

    positions = lib.get_all_positions()

    assert positions == ()
    assert state["reattaches"] == 0
