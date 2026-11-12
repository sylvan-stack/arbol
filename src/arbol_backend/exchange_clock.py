"""Deadlines that exclude Mac sleep, with monotonic fallback on other platforms."""

import time


def awake() -> float:
    return time.clock_gettime(getattr(time, 'CLOCK_UPTIME_RAW', time.CLOCK_MONOTONIC))
