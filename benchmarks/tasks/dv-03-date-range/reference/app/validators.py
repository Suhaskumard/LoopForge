import re
from datetime import date

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse(value: str) -> date:
    text = value.strip() if isinstance(value, str) else ""
    if not _ISO.match(text):
        raise ValueError(f"not an ISO date: {value!r}")
    return date.fromisoformat(text)


def parse_date_range(start: str, end: str) -> tuple[date, date]:
    s, e = _parse(start), _parse(end)
    if e < s:
        raise ValueError("end is before start")
    return s, e


def days_inclusive(start: str, end: str) -> int:
    s, e = parse_date_range(start, end)
    return (e - s).days + 1
