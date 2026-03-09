"""Tests for async utility functions."""

import asyncio
import time

from fastapi_task_manager.async_utils import interruptible_sleep


class TestInterruptibleSleep:
    """Tests for interruptible_sleep."""

    async def test_sleeps_full_duration_when_should_continue_true(self):
        """Completes the full sleep when should_continue always returns True."""
        start = time.monotonic()
        await interruptible_sleep(0.2, lambda: True, step=0.05)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.2

    async def test_exits_early_when_should_continue_false(self):
        """Exits before full duration when should_continue returns False."""
        start = time.monotonic()
        await interruptible_sleep(5.0, lambda: False, step=0.05)
        elapsed = time.monotonic() - start
        # Should exit almost immediately (within one step)
        assert elapsed < 0.5

    async def test_exits_on_flag_change(self):
        """Exits when the flag transitions from True to False mid-sleep."""
        running = True

        async def stop_after_delay():
            nonlocal running
            await asyncio.sleep(0.15)
            running = False

        bg_task = asyncio.create_task(stop_after_delay())  # noqa: F841, RUF006
        start = time.monotonic()
        await interruptible_sleep(5.0, lambda: running, step=0.05)
        elapsed = time.monotonic() - start
        # Should exit shortly after the flag flips (~0.15 + one step)
        assert elapsed < 1.0

    async def test_zero_duration_returns_immediately(self):
        """A zero-second sleep returns without looping."""
        start = time.monotonic()
        await interruptible_sleep(0, lambda: True, step=0.05)
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    async def test_step_larger_than_seconds(self):
        """When step > seconds, sleeps for exactly the remaining amount."""
        start = time.monotonic()
        await interruptible_sleep(0.1, lambda: True, step=10.0)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.1
        assert elapsed < 0.5
