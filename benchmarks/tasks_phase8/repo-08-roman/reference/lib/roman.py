VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_to_int(text):
    if not text or any(c not in VALUES for c in text):
        raise ValueError(text)
    total = 0
    for i, c in enumerate(text):
        if i + 1 < len(text) and VALUES[c] < VALUES[text[i + 1]]:
            total -= VALUES[c]
        else:
            total += VALUES[c]
    return total
