def moving_average(values, window):
    if window < 1 or window > len(values):
        raise ValueError("window")
    return [sum(values[i : i + window]) / window for i in range(len(values) - window)]
