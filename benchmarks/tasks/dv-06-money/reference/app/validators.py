import re
from decimal import Decimal

_PATTERN = re.compile(r"^\$?(\d{1,3}(,\d{3})+|\d+)(\.\d{1,2})?$")
_MAX = Decimal("1000000000.00")


def parse_money(text: str) -> Decimal:
    if not isinstance(text, str) or not _PATTERN.match(text.strip()):
        raise ValueError(f"invalid amount: {text!r}")
    amount = Decimal(text.strip().lstrip("$").replace(",", "")).quantize(Decimal("0.01"))
    if amount > _MAX:
        raise ValueError("amount too large")
    return amount


def format_money(amount: Decimal) -> str:
    return "$" + f"{Decimal(amount).quantize(Decimal('0.01')):,.2f}"
