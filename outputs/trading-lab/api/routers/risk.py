from fastapi import APIRouter
from pydantic import BaseModel, Field

from risk.gate import GATE

router = APIRouter(prefix="/api/live", tags=["risk"])


class ArmBody(BaseModel):
    hours: float | None = Field(default=None, ge=0.1, le=72)


@router.get("/status")
async def live_status():
    return GATE.status()


@router.post("/arm")
async def live_arm(body: ArmBody | None = None):
    hours = body.hours if body else None
    return GATE.arm(hours)


@router.post("/disarm")
async def live_disarm():
    return GATE.disarm()
