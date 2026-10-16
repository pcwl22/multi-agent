def paginate(items, page, page_size):
    if page < 1 or page_size < 1:
        return []
    start = page * page_size
    return items[start : start + page_size]
