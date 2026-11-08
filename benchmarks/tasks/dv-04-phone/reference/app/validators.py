import re


def normalize_phone(raw: str, default_country_code: str = "1") -> str:
    if not isinstance(raw, str):
        raise ValueError("phone must be a string")
    text = raw.strip()
    if not text:
        raise ValueError("empty")
    plus = text.startswith("+")
    body = re.sub(r"[ .\-()]", "", text[1:] if plus else text)
    if not body.isdigit():
        raise ValueError("invalid characters")
    if plus or body.startswith("00"):
        digits = body if plus else body[2:]
        if not 8 <= len(digits) <= 14 or digits.startswith("0"):
            raise ValueError("invalid international number")
        return "+" + digits
    national = body[1:] if body.startswith("0") else body
    if default_country_code == "1":
        if len(national) != 10:
            raise ValueError("national number must have 10 digits")
    elif not 6 <= len(national) <= 12:
        raise ValueError("bad national length")
    return "+" + default_country_code + national
