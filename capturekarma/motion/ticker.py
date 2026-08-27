"""Drift-corrected fixed-rate ticker."""
from __future__ import annotations

import time
from typing import Callable, Iterator


class Ticker:
    def __init__(self, hz: int = 120, clock: Callable[[], float] = time.perf_counter,
                 sleep: Callable[[float], None] = time.sleep, spin_threshold: float = 0.002):
        if hz <= 0:
            raise ValueError("hz must be positive")
        self.hz = hz
        self._clock = clock
        self._sleep = sleep
        self._spin = spin_threshold

    def now(self) -> float:
        """Current time from the injected clock (the player uses this for timeline timestamps)."""
        return self._clock()

    def n_ticks(self, duration: float) -> int:
        return max(1, round(duration * self.hz))

    def sleep_until(self, deadline: float) -> None:
        """Sleep in coarse steps until the deadline; the last step is a short, precise one."""
        while True:
            remaining = deadline - self._clock()
            if remaining <= 0:
                return
            if remaining <= 2 * self._spin:
                # Final step: sleep the whole remainder and stop. Looping once more would spin on a
                # rounding residue (a few 1e-18 s) whose sleep is too small to move the clock at all.
                self._sleep(remaining)
                return
            self._sleep(remaining - self._spin)

    def ticks(self, duration: float) -> Iterator[tuple[int, float]]:
        """Yield (i, i/n) for i in 1..n at deadlines start + i/hz. Late ticks are not slept for."""
        n = self.n_ticks(duration)
        start = self._clock()
        for i in range(1, n + 1):
            deadline = start + i / self.hz if duration > 0 else start
            self.sleep_until(deadline)
            yield i, i / n

    def wait(self, seconds: float) -> None:
        if seconds <= 0:
            return
        self.sleep_until(self._clock() + seconds)
