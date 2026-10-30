"""
Today router — stub for Phase 2.
Returns a clear 'not_implemented' response so callers know this is intentional,
not a broken endpoint.
"""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/today", tags=["today"])


class StubResponse(BaseModel):
    status: str
    message: str
    phase: str


@router.get("/announcements", response_model=StubResponse)
def get_announcements() -> StubResponse:
    """Phase 2 — NSE announcement feed + LLM classification. Not yet implemented."""
    return StubResponse(
        status="not_implemented",
        message="Corporate announcement feed will be available in Phase 2.",
        phase="2",
    )


@router.post("/refresh", response_model=StubResponse)
def refresh_announcements() -> StubResponse:
    """Phase 2 stub."""
    return StubResponse(
        status="not_implemented",
        message="NSE feed refresh will be available in Phase 2.",
        phase="2",
    )
