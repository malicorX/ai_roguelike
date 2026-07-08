from __future__ import annotations

import re

_DURATION_PATTERN = re.compile(r"^(\d+)([smh])$", re.IGNORECASE)


def parse_duration(value: str) -> int:
    match = _DURATION_PATTERN.match(value.strip())
    if not match:
        raise ValueError(f"Unsupported duration format: {value!r} (use e.g. 30m, 12h, 45s)")
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit == "s":
        return amount
    if unit == "m":
        return amount * 60
    return amount * 3600
