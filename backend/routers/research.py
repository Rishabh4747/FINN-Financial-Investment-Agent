"""
Research router — stub for Phase 3.
Returns a clear 'not_implemented' response.
"""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/research", tags=["research"])


class StubResponse(BaseModel):
    status: str
    message: str
    phase: str


@router.post("/report", response_model=StubResponse)
def generate_report() -> StubResponse:
    """Phase 3 — Document fetch + LLM research report. Not yet implemented."""
    return StubResponse(
        status="not_implemented",
        message="Research report generation will be available in Phase 3.",
        phase="3",
    )


@router.get("/documents/{ticker}", response_model=StubResponse)
def list_documents(ticker: str) -> StubResponse:
    """Phase 3 stub."""
    return StubResponse(
        status="not_implemented",
        message=f"Document listing for {ticker} will be available in Phase 3.",
        phase="3",
    )
