def paginate(items: list[int], page: int, page_size: int) -> list[int]:
    start = page * page_size
    return items[start : start + page_size]
