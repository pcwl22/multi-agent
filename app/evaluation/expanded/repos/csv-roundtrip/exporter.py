def export_rows(rows):
    return "".join(",".join(str(cell) for cell in row) + "\n" for row in rows)
