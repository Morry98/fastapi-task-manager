"""Async utility functions shared across stream mode components."""

import asyncio
from collections.abc import Callable


async def interruptible_sleep(
    seconds: float,
    should_continue: Callable[[], bool],
    step: float = 0.5,
) -> None:
    """Sleep for the given duration, exiting early if should_continue returns False.

    Instead of a single long sleep that blocks shutdown, this function sleeps
    in short increments and checks the condition between each one.

    Args:
        seconds: Total sleep duration in seconds.
        should_continue: Callable that returns True while the loop should keep sleeping.
            Typically a lambda referencing the component's _running or _is_leader flag.
        step: Maximum duration of each individual sleep increment in seconds.
            Smaller values give faster shutdown response at the cost of more wakeups.
    """
    remaining = seconds
    while remaining > 0 and should_continue():
        await asyncio.sleep(min(step, remaining))
        remaining -= step
