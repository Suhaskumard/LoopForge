def apply_discount(price, percent):
    return price - percent


def total(items):
    return sum(i["price"] * i["qty"] for i in items)
