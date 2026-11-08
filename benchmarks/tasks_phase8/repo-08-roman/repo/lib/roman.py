VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_to_int(text):
    if not text or any(c not in VALUES for c in text):
        raise ValueError(text)
    return sum(VALUES[c] for c in text)
