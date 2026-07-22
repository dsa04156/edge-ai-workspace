from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AxisName = Literal["x", "y", "z"]


@dataclass(frozen=True)
class AxisSample:
    origin: int
    value_type: str
    value: int


@dataclass(frozen=True)
class AccelerationFrame:
    origin: int
    x: int
    y: int
    z: int


@dataclass
class JoinCounters:
    duplicates_ignored: int = 0
    incomplete_frames_dropped: int = 0
