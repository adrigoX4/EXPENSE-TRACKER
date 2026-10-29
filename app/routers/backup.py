from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.config import settings
from app.database import get_db
from app.errors import AppError, ValidationError
from app.schemas import BackupInfo
from app.services.backup import (
    backup_info,
    create_snapshot,
    restore_from_file,
    validate_sqlite_file,
)

router = APIRouter(prefix="/api/backup", tags=["backup"])

MAX_UPLOAD_BYTES = 250 * 1024 * 1024


def _save_upload(upload: UploadFile) -> Path:
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(upload.filename or "backup.db").suffix or ".db"
    target = settings.uploads_dir / f"upload-{uuid4().hex}{suffix}"
    total = 0
    with target.open("wb") as handle:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                handle.close()
                target.unlink(missing_ok=True)
                raise AppError("Backup file is larger than the 250 MB limit.", status_code=413)
            handle.write(chunk)
    if total == 0:
        target.unlink(missing_ok=True)
        raise ValidationError("The uploaded file is empty")
    return target


@router.get("/info", response_model=BackupInfo)
def info(db: Session = Depends(get_db)):
    return backup_info(db)


@router.post("/create")
def create(db: Session = Depends(get_db)):
    return create_snapshot(db, prefix="manual")


@router.get("/download")
def download(db: Session = Depends(get_db)):
    snapshot = create_snapshot(db, prefix="download")
    path = Path(snapshot["path"])
    return FileResponse(
        path,
        media_type="application/x-sqlite3",
        filename=path.name,
        background=BackgroundTask(lambda: path.unlink(missing_ok=True)),
    )


@router.post("/validate")
def validate(upload: UploadFile = File(...)):
    path = _save_upload(upload)
    try:
        return validate_sqlite_file(path)
    finally:
        path.unlink(missing_ok=True)


@router.post("/restore")
def restore(
    upload: UploadFile = File(...),
    confirm: str = Query(...),
    db: Session = Depends(get_db),
):
    if confirm != "REPLACE":
        raise ValidationError('Type REPLACE in the confirmation field to restore a backup.')
    path = _save_upload(upload)
    try:
        return restore_from_file(db, path)
    finally:
        path.unlink(missing_ok=True)
