import re


def parse_duration(text):
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", text)
    if not text or not m:
        raise ValueError(text)
    h, mi, s = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mi * 60 + s
