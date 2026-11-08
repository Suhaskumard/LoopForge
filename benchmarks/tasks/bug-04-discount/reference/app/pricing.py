from decimal import ROUND_HALF_UP, Decimal


def _d(x):
    return Decimal(str(x))


def apply_discount(price, percent):
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    result = _d(price) * (Decimal(100) - _d(percent)) / Decimal(100)
    return float(result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def total(items):
    return float(sum((_d(i["price"]) * i["qty"] for i in items), Decimal(0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
