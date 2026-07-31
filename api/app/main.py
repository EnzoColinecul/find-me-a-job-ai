import logging

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mangum import Mangum

logger = logging.getLogger("fmaj")

from app.auth import AuthUser, require_user
from app.searches import QuotaExhausted, SearchRequest, create_search, get_search
from app.settings import settings
from app.users import ensure_user

app = FastAPI(title="Find-Me-A-Job AI API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return JSON 500s through the middleware stack so CORS headers are applied.

    Without this, unhandled exceptions bypass CORSMiddleware and the browser reports
    an opaque 'Failed to fetch' instead of the real error.
    """
    logger.exception("Unhandled error on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": f"Internal error: {type(exc).__name__}"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "stage": settings.stage}


@app.get("/me")
def me(user: AuthUser = Depends(require_user)) -> dict:
    """Return the signed-in user's profile, creating it on first sign-in."""
    profile = ensure_user(user.sub, user.email, user.name)
    return {
        "sub": user.sub,
        "email": profile["email"],
        "name": profile.get("name") or None,
        "free_search_used": profile["free_search_used"],
    }


@app.post("/searches", status_code=201)
def post_search(req: SearchRequest, user: AuthUser = Depends(require_user)) -> dict:
    try:
        meta = create_search(user.sub, req)
    except QuotaExhausted:
        raise HTTPException(
            status_code=402,
            detail="Your free search has been used. Subscriptions are coming soon!",
        ) from None
    return {"search_id": meta["search_id"], "status": meta["status"]}


@app.get("/searches/{search_id}")
def get_search_route(search_id: str, user: AuthUser = Depends(require_user)) -> dict:
    found = get_search(user.sub, search_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Search not found")
    return found


# TODO(Phase 4): GET /searches/{search_id}/report — presigned PDF URL.

# Lambda entrypoint
handler = Mangum(app)
