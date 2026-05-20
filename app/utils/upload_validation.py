from pathlib import Path

from fastapi import UploadFile

ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png"}
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/jpg"}


def validate_upload_file(file: UploadFile) -> str:
    """Zwraca suffix bez kropki, np. 'jpg'. Rzuca HTTPException 400."""
    if not file.filename:
        raise ValueError("Filename is required")
    # validate suffix
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError("Unsupported file type")
    # validate file type
    if file.content_type and file.content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError("Unsupported file type")
    return suffix.lstrip(".")
