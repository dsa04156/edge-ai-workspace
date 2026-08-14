from __future__ import annotations


JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonMap = dict[str, JsonValue]
