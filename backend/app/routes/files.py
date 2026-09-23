"""Folder browsing, file open/download, and search.

Every user can see every folder, exactly like a real shared org drive: the
restriction here is behavioural, not an access wall. Reaching into another
role's folder is logged and scored, not blocked.

Nothing in this module ever tells the client whether a file is a honeyfile,
and nothing tells it that a session has been switched into decoy mode - the
poisoned response is shaped exactly like the real one.
"""
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from app.auth import get_current
from app.database import get_db
from app.detection import decoy_generator, risk_engine
from app.models import File, Folder, User, UserSession

router = APIRouter(tags=["files"])


class FolderOut(BaseModel):
    id: int
    name: str
    file_count: int


class FileOut(BaseModel):
    id: int
    filename: str
    folder_id: int
    folder_name: str
    extension: str


class FileContentOut(BaseModel):
    id: int
    filename: str
    folder_name: str
    content: str


class SearchRequest(BaseModel):
    query: str


class SearchResponse(BaseModel):
    query: str
    results: List[FileOut]


def _extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _file_out(f: File) -> FileOut:
    return FileOut(
        id=f.id,
        filename=f.filename,
        folder_id=f.folder_id,
        folder_name=f.folder.name if f.folder else "",
        extension=_extension(f.filename),
    )


def _get_file_or_404(db: DbSession, file_id: int) -> File:
    f = db.query(File).filter(File.id == file_id).first()
    if f is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        )
    return f


@router.get("/folders", response_model=List[FolderOut])
def list_folders(
    current: Tuple[User, UserSession] = Depends(get_current),
    db: DbSession = Depends(get_db),
):
    folders = db.query(Folder).order_by(Folder.id).all()
    return [
        FolderOut(id=f.id, name=f.name, file_count=len(f.files)) for f in folders
    ]


@router.get("/folders/{folder_id}/files", response_model=List[FileOut])
def list_files(
    folder_id: int,
    current: Tuple[User, UserSession] = Depends(get_current),
    db: DbSession = Depends(get_db),
):
    folder = db.query(Folder).filter(Folder.id == folder_id).first()
    if folder is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found"
        )
    files = (
        db.query(File).filter(File.folder_id == folder.id).order_by(File.filename).all()
    )
    # Browsing a folder listing is not itself a scored action.
    return [_file_out(f) for f in files]


@router.post("/files/{file_id}/open", response_model=FileContentOut)
def open_file(
    file_id: int,
    current: Tuple[User, UserSession] = Depends(get_current),
    db: DbSession = Depends(get_db),
):
    user, session = current
    f = _get_file_or_404(db, file_id)

    # Active response: once this session is in decoy mode every file it opens
    # comes back fake, honeyfile or not. The stored row is left untouched.
    poisoned = bool(session.decoy_mode)
    if not poisoned:
        decoy_generator.ensure_decoy_content(db, f)

    action_type, points, reason = risk_engine.score_open(db, session, user, f)
    risk_engine.record_action(
        db,
        session=session,
        user=user,
        action_type=action_type,
        points=points,
        reason=reason,
        file=f,
    )
    db.commit()

    return FileContentOut(
        id=f.id,
        filename=f.filename,
        folder_name=f.folder.name if f.folder else "",
        content=decoy_generator.poisoned_content(f) if poisoned else f.content,
    )


@router.post("/files/{file_id}/download")
def download_file(
    file_id: int,
    current: Tuple[User, UserSession] = Depends(get_current),
    db: DbSession = Depends(get_db),
):
    user, session = current
    f = _get_file_or_404(db, file_id)

    poisoned = bool(session.decoy_mode)
    if not poisoned:
        decoy_generator.ensure_decoy_content(db, f)

    action_type, points, reason = risk_engine.score_download(db, session, user, f)
    risk_engine.record_action(
        db,
        session=session,
        user=user,
        action_type=action_type,
        points=points,
        reason=reason,
        file=f,
    )
    db.commit()

    # Content is plain text regardless of the extension shown in the UI.
    return Response(
        content=decoy_generator.poisoned_content(f) if poisoned else f.content,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="%s"' % f.filename,
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.post("/search", response_model=SearchResponse)
def search(
    payload: SearchRequest,
    current: Tuple[User, UserSession] = Depends(get_current),
    db: DbSession = Depends(get_db),
):
    user, session = current
    query = (payload.query or "").strip()

    action_type, points, reason = risk_engine.score_search(query)
    risk_engine.record_action(
        db,
        session=session,
        user=user,
        action_type=action_type,
        points=points,
        reason=reason,
        search_query=query,
    )
    db.commit()

    results: List[File] = []
    if query:
        results = (
            db.query(File)
            .filter(File.filename.ilike("%%%s%%" % query))
            .order_by(File.filename)
            .all()
        )
    return SearchResponse(query=query, results=[_file_out(f) for f in results])
