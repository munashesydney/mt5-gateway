from collections import namedtuple

import lib

Position = namedtuple("Position", "ticket type magic")


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
