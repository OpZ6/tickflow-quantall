"""Optional local Chanlun workbench integration."""
from __future__ import annotations

from fastapi import APIRouter

from app.services.chanlun_bridge import get_status

router = APIRouter(prefix="/api/chanlun", tags=["chanlun"])


@router.get("/status")
def chanlun_status():
    """Report whether the separately isolated local Chanlun engine is ready."""
    return get_status()
