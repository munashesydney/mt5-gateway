"""Bounded quote readiness checks before any order is submitted."""

import math
import time
from typing import Any, Callable, Optional


def wait_for_market_quote(
    read_tick: Callable[[], Any],
    timeout_s: float,
    *,
    clock: Callable[[], float] = time.monotonic,
    pause: Callable[[float], None] = time.sleep,
) -> Optional[Any]:
    """Wait briefly for both sides of a broker quote to become usable.

    Args:
        read_tick: Native quote reader for the selected symbol.
        timeout_s: Maximum wait, bounded by the execution deadline by the caller.
        clock: Monotonic clock, injectable for deterministic checks.
        pause: Sleep implementation, injectable for deterministic checks.

    Returns:
        The broker tick, or None if a usable quote never arrives.
    """
    deadline = clock() + max(0.0, timeout_s)
    while True:
        tick = read_tick()
        try:
            bid, ask = float(tick.bid), float(tick.ask)
            if math.isfinite(bid) and math.isfinite(ask) and 0 < bid <= ask:
                return tick
        except (AttributeError, TypeError, ValueError, OverflowError):
            pass
        remaining = deadline - clock()
        if remaining <= 0:
            return None
        pause(min(0.05, remaining))
