from fastapi import APIRouter, Depends
from database import get_mentions

router = APIRouter()

@router.get("/dashboard_data")
async def dashboard_data():
    mentions = await get_mentions()
    return {"mentions": mentions}
