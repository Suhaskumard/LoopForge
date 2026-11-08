import re


def _clean(number: str) -> str:
    return re.sub(r"[ -]", "", number) if isinstance(number, str) else ""


def luhn_valid(number: str) -> bool:
    digits = _clean(number)
    if not digits.isdigit() or not 12 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def mask_card(number: str) -> str:
    if not luhn_valid(number):
        raise ValueError("invalid card number")
    digits = _clean(number)
    return "*" * (len(digits) - 4) + digits[-4:]
