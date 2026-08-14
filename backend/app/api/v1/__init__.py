from fastapi import APIRouter

from app.api.v1 import admissions, auth, notes, patients

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(patients.router, prefix="/patients", tags=["patients"])
api_router.include_router(admissions.router, prefix="/admissions", tags=["admissions"])
api_router.include_router(notes.router, prefix="/notes", tags=["notes"])
