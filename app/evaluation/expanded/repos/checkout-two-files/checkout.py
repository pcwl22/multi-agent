from money import discounted


def invoice_total(amount, discount_percent, tax_rate):
    subtotal = discounted(amount, discount_percent)
    return round(subtotal + amount * tax_rate, 2)
