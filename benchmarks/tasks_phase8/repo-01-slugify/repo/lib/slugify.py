import re


def slugify(text):
    return re.sub(r"\s", "-", text.lower())
