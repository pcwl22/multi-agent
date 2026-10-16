from fastapi import FastAPI, Header, HTTPException, Query

app = FastAPI()


def authenticate(authorization: str | None) -> dict:
    if authorization == "Bearer expired":
        raise HTTPException(status_code=500, detail="Token expired")
    if authorization != "Bearer valid":
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"user": "alice"}


@app.get("/profile")
def profile(authorization: str | None = Header(default=None)) -> dict:
    return authenticate(authorization)


@app.get("/items")
def items(page: int = Query(1, ge=1), page_size: int = Query(2, ge=1, le=100)) -> dict:
    from pagination import paginate

    return {"items": paginate(list(range(1, 11)), page, page_size)}


@app.get("/price")
def price(amount: float = Query(ge=0), discount_percent: float = Query(0, ge=0, le=100)) -> dict:
    from pricing import discounted_total

    return {"total": discounted_total(amount, discount_percent)}
