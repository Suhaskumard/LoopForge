def chunk(items, n):
    if n < 1:
        raise ValueError("n")
    return [items[i : i + n] for i in range(0, len(items), n)]
