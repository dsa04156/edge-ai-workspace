from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class Measurement(ContractModel):
    value: float
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    quality: Literal["good", "uncertain", "bad"] = "good"

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("measurement value must be finite")
        return value


class ProductionContext(ContractModel):
    production_id: str = Field(min_length=1, max_length=128)
    lot_id: str | None = Field(default=None, min_length=1, max_length=128)
    product_code: str | None = Field(default=None, min_length=1, max_length=128)


class PumpMotorSignals(ContractModel):
    acceleration_x: Measurement
    acceleration_y: Measurement
    acceleration_z: Measurement
    temperature: Measurement
    additional: dict[str, Measurement] = Field(default_factory=dict)

    @field_validator("additional")
    @classmethod
    def validate_additional_names(
        cls,
        values: dict[str, Measurement],
    ) -> dict[str, Measurement]:
        for name in values:
            if not name.strip() or len(name) > 128:
                raise ValueError(
                    "additional measurement names must be 1-128 characters"
                )
        return values


class PumpMotorTelemetry(ContractModel):
    """Versioned input contract for the first Okdong anomaly-service slice.

    The four named signals are the currently executable baseline. Field-specific
    PLC addresses, engineering units and optional current/pressure/RPM signals
    remain mapping configuration until the Okdong data inventory is confirmed.
    """

    schema_version: Literal["okdong.pump-motor.telemetry/v1"] = (
        "okdong.pump-motor.telemetry/v1"
    )
    event_id: str = Field(min_length=1, max_length=128)
    source_type: Literal["sensor", "simulator", "replay"]
    device_id: str = Field(min_length=1, max_length=128)
    asset_id: str = Field(min_length=1, max_length=128)
    node_id: str | None = Field(default=None, min_length=1, max_length=128)
    observed_at: datetime
    signals: PumpMotorSignals
    production: ProductionContext | None = None
    attributes: dict[str, str] = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observedAt must include a timezone")
        return value

    @field_validator("attributes")
    @classmethod
    def validate_attributes(cls, values: dict[str, str]) -> dict[str, str]:
        if len(values) > 32:
            raise ValueError("attributes must contain at most 32 entries")
        for key, value in values.items():
            if not key.strip() or len(key) > 64 or len(value) > 256:
                raise ValueError("attribute keys or values exceed contract limits")
        return values


class ProductionQualityTelemetry(ContractModel):
    """Versioned envelope for PLC/MES production-quality correlation.

    Process field names intentionally remain a validated map. The actual Okdong
    PLC tags, MES columns and label timing have not been supplied yet and must not
    be invented in the executable contract.
    """

    schema_version: Literal["okdong.production-quality.telemetry/v1"] = (
        "okdong.production-quality.telemetry/v1"
    )
    event_id: str = Field(min_length=1, max_length=128)
    source_type: Literal["plc", "mes", "sensor", "simulator", "replay"]
    line_id: str = Field(min_length=1, max_length=128)
    observed_at: datetime
    production: ProductionContext
    process_values: dict[str, Measurement] = Field(min_length=1)
    quality_label: Literal["good", "defective", "unknown"] | None = None
    attributes: dict[str, str] = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observedAt must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_process_names(self) -> ProductionQualityTelemetry:
        for name in self.process_values:
            if not name.strip() or len(name) > 128:
                raise ValueError("process value names must be 1-128 characters")
        return self


def contract_schemas() -> dict[str, dict]:
    return {
        "pump-motor": PumpMotorTelemetry.model_json_schema(by_alias=True),
        "production-quality": ProductionQualityTelemetry.model_json_schema(
            by_alias=True
        ),
    }
