"""
time_control.py

Shared temporal monitor for target-duration storytelling.

This version tries to make the story last approximately the target duration.

Pacing modes:
    too_fast -> story is ahead of schedule, expand current beat
    normal   -> story is on schedule
    hurry    -> story is slightly behind
    critical -> story is far behind
    final    -> almost out of time, end now
"""

import time


class TemporalMonitor:
    def __init__(
        self,
        time_limit_minutes: float,
        total_beats: int,
        final_buffer_seconds: float = 30.0,
        too_fast_margin: float = 0.15,
        hurry_margin: float = 0.15,
        critical_margin: float = 0.30,
    ):
        self.start_time = time.time()
        self.time_limit_seconds = time_limit_minutes * 60
        self.total_beats = total_beats
        self.final_buffer_seconds = final_buffer_seconds

        self.too_fast_margin = too_fast_margin
        self.hurry_margin = hurry_margin
        self.critical_margin = critical_margin

    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time

    def remaining_seconds(self) -> float:
        return max(0.0, self.time_limit_seconds - self.elapsed_seconds())

    def expected_progress(self) -> float:
        if self.time_limit_seconds <= 0:
            return 1.0
        return min(1.0, self.elapsed_seconds() / self.time_limit_seconds)

    def actual_progress(self, beat_index: int) -> float:
        if self.total_beats <= 0:
            return 1.0
        return min(1.0, beat_index / self.total_beats)

    def pacing_mode(self, beat_index: int) -> str:
        remaining = self.remaining_seconds()
        expected = self.expected_progress()
        actual = self.actual_progress(beat_index)

        if remaining <= self.final_buffer_seconds:
            return "final"

        if actual - expected >= self.too_fast_margin:
            return "too_fast"

        if expected - actual >= self.critical_margin and beat_index >= 1:
            return "critical"

        if expected - actual >= self.hurry_margin:
            return "hurry"

        return "normal"

    def should_stop_for_time(self) -> bool:
        return self.remaining_seconds() <= 0

    def should_allow_story_closure(self, beat_index: int) -> bool:
        near_final_beat = beat_index >= self.total_beats - 1
        almost_out_of_time = self.remaining_seconds() <= self.final_buffer_seconds
        return near_final_beat or almost_out_of_time

    def state(self, beat_index: int, beats: list) -> dict:
        remaining_beats = beats[beat_index:] if beat_index < len(beats) else []

        return {
            "elapsed_seconds": round(self.elapsed_seconds(), 2),
            "remaining_seconds": round(self.remaining_seconds(), 2),
            "time_limit_seconds": round(self.time_limit_seconds, 2),
            "current_beat_index": beat_index,
            "total_beats": self.total_beats,
            "completed_beats_count": beat_index,
            "remaining_beats_count": len(remaining_beats),
            "expected_progress": round(self.expected_progress(), 2),
            "actual_progress": round(self.actual_progress(beat_index), 2),
            "pacing_mode": self.pacing_mode(beat_index),
            "remaining_beats": remaining_beats,
        }