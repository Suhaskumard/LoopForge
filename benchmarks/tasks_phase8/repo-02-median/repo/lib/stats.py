def median(values):
    if not values:
        raise ValueError("empty")
    s = sorted(values)
    return s[len(s) // 2]
