from types import SimpleNamespace

from market_quote import wait_for_market_quote


def test_waits_for_positive_finite_quote_after_login():
    ticks = iter(
        [None, SimpleNamespace(bid=0, ask=0), SimpleNamespace(bid=3701, ask=3702)]
    )
    clock = [0.0]
    pauses = []

    def pause(seconds):
        pauses.append(seconds)
        clock[0] += seconds

    quote = wait_for_market_quote(
        lambda: next(ticks), 2, clock=lambda: clock[0], pause=pause
    )
    assert quote.ask == 3702
    assert len(pauses) == 2


def test_invalid_quotes_stop_at_budget_without_inventing_a_price():
    clock = [0.0]

    def pause(seconds):
        clock[0] += seconds

    quote = wait_for_market_quote(
        lambda: SimpleNamespace(bid=float("nan"), ask=0),
        0.2,
        clock=lambda: clock[0],
        pause=pause,
    )
    assert quote is None
    assert clock[0] == 0.2


def test_zero_budget_reads_once_without_sleeping():
    def no_sleep(_):
        raise AssertionError("No time remains")

    assert (
        wait_for_market_quote(lambda: SimpleNamespace(bid=0, ask=0), 0, pause=no_sleep)
        is None
    )
