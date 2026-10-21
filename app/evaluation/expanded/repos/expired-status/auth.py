def authenticate(token):
    if token == "expired":
        return 500, "expired"
    if token == "valid":
        return 200, "alice"
    return 401, "missing"
