from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from app.settings import settings

app = FastAPI(title="Find-Me-A-Job AI API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "stage": settings.stage}


# TODO(Phase 1): POST /searches — validate params, enforce free-search quota
#                (DynamoDB conditional update), start Step Functions execution.
# TODO(Phase 1): GET /searches/{search_id} — status + incremental results.
# TODO(Phase 4): GET /searches/{search_id}/report — presigned PDF URL.

# Lambda entrypoint
handler = Mangum(app)
