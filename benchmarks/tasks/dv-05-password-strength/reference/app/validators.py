COMMON = {"password", "123456789012", "qwertyuiop12", "letmein12345"}


def check_password(password: str, username: str = "") -> list[str]:
    out: list[str] = []
    if len(password) < 12:
        out.append("too_short")
    if not any(c.isupper() for c in password):
        out.append("no_upper")
    if not any(c.islower() for c in password):
        out.append("no_lower")
    if not any(c.isdigit() for c in password):
        out.append("no_digit")
    if all(c.isalnum() for c in password):
        out.append("no_symbol")
    if any(c.isspace() for c in password):
        out.append("has_space")
    if username and username.lower() in password.lower():
        out.append("contains_username")
    if password.lower() in COMMON:
        out.append("common")
    return out
