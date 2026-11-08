def word_count(text):
    counts = {}
    for w in text.lower().split():
        counts[w] = counts.get(w, 0) + 1
    return counts
