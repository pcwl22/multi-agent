def available_units(stock, reservations):
    reserved = dict(reservations)
    return {sku: max(0, qty - reserved.get(sku, 0)) for sku, qty in stock.items()}
