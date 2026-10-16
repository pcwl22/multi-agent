from fastapi import FastAPI, Header, HTTPException

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
