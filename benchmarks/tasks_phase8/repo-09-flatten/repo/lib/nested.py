def flatten(items):
    out = []
    for x in items:
        if isinstance(x, (list, tuple)):
            out.extend(x)
        else:
            out.append(x)
    return out
