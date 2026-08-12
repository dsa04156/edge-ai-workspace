from __future__ import annotations

import json
import math
from datetime import datetime
from enum import Enum
from typing import Any

from .config import DeviceProfile, PropertyMapping
from .models import DataPoint, NormalizedSample, Quality


class Normalizer:
    def __init__(self, profile: DeviceProfile) -> None:
        self.profile = profile

    def normalize(self, raw: dict[str, Any], *, collected_at: int) -> NormalizedSample:
        if not isinstance(raw, dict):
            raise TypeError("raw sample must be a mapping")

        source_timestamp = self._source_timestamp(raw)
        errors: list[str] = []
        if source_timestamp is None:
            errors.append("missing_source_timestamp")

        data: dict[str, DataPoint] = {}
        for source_name, property_mapping in self.profile.mapping.properties.items():
            if source_name not in raw or raw[source_name] is None:
                if property_mapping.required:
                    errors.append(f"missing_required_property:{source_name}")
                continue
            try:
                value = _convert_value(raw[source_name], property_mapping)
            except (TypeError, ValueError):
                errors.append(f"invalid_property:{source_name}:{property_mapping.value_type}")
                continue
            data[property_mapping.target] = DataPoint(value=value, unit=property_mapping.unit)

        return NormalizedSample(
            source_timestamp=source_timestamp,
            collected_at=int(collected_at),
            data=data,
            quality=Quality(valid=not errors, errors=tuple(errors)),
        )

    def _source_timestamp(self, raw: dict[str, Any]) -> Any:
        for field_name in self.profile.mapping.timestamp_fields:
            value = raw.get(field_name)
            if value not in (None, ""):
                return value
        return None


class SampleDecision(str, Enum):
    NEW = "new"
    DUPLICATE = "duplicate"
    STALE = "stale"


class SampleGuard:
    """Suppress exact repeats and samples older than the last comparable source time."""

    def __init__(self) -> None:
        self._last_timestamp_key: str | None = None
        self._last_comparable_timestamp: float | None = None
        self._last_fingerprint: str | None = None

    def check(self, source_timestamp: Any, data: Any) -> SampleDecision:
        timestamp_key = _canonical(source_timestamp)
        fingerprint = _canonical(data)
        comparable_timestamp = _comparable_timestamp(source_timestamp)

        if (
            self._last_timestamp_key == timestamp_key
            and self._last_fingerprint == fingerprint
        ):
            return SampleDecision.DUPLICATE

        if (
            comparable_timestamp is not None
            and self._last_comparable_timestamp is not None
            and comparable_timestamp < self._last_comparable_timestamp
        ):
            return SampleDecision.STALE

        self._last_timestamp_key = timestamp_key
        self._last_comparable_timestamp = comparable_timestamp
        self._last_fingerprint = fingerprint
        return SampleDecision.NEW


def _convert_value(value: Any, mapping: PropertyMapping) -> Any:
    value_type = mapping.value_type
    if value_type == "float":
        if isinstance(value, bool):
            raise TypeError("boolean is not a float sample")
        converted = float(value)
        if not math.isfinite(converted):
            raise ValueError("float sample must be finite")
        return converted

    if value_type == "int":
        if isinstance(value, bool):
            raise TypeError("boolean is not an integer sample")
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if not value.is_integer():
                raise ValueError("integer sample has a fractional part")
            return int(value)
        text = str(value).strip()
        if not text or any(character in text for character in (".", "e", "E")):
            raise ValueError("integer sample is not integral")
        return int(text)

    if value_type == "string":
        if isinstance(value, (dict, list, tuple, set)):
            raise TypeError("structured value is not a string sample")
        return str(value)

    if value_type == "bool":
        if isinstance(value, bool):
            return value
        if value in (0, 1):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        raise ValueError("boolean sample is not recognized")

    raise ValueError(f"unsupported mapping type: {value_type}")


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _comparable_timestamp(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    if isinstance(value, datetime):
        return value.timestamp()
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return parsed if math.isfinite(parsed) else None
