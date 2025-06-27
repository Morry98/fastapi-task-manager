import asyncio
from contextlib import asynccontextmanager


class ForceAcquireSemaphore(asyncio.Semaphore):
    @asynccontextmanager
    async def force_acquire(self):
        # bypass the normal acquire() wait and
        # decrement the counter even if it goes < 0
        self._value -= 1
        try:
            yield
        finally:
            if self._value < 0:
                # if the value is negative, we increment it back
                self._value += 1
            else:
                # if the value is not negative, we just release normally
                # this is to ensure that the semaphore can be used normally after force_acquire
                self.release()
