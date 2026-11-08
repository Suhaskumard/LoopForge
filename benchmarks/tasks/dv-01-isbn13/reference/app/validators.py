import re


def is_valid_isbn13(value: str) -> bool:
    if not isinstance(value, str):
        return False
    digits = re.sub(r"[-\s]", "", value)
    if len(digits) != 13 or not digits.isdigit():
        return False
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits))
    return total % 10 == 0
