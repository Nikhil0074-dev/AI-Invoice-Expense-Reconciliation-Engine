from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import Ctx, require
from app.core.errors import AppError
from app.integrations.storage import get_storage
from app.models import ExportRecord
from app.schemas import ExportIn, ExportOut
from app.services import export_service

router = APIRouter(prefix="/exports", tags=["exports"])


def _out(e: ExportRecord) -> ExportOut:
    o = ExportOut.model_validate(e)
    o.download_url = f"/api/v1/exports/{e.id}/download"
    return o


@router.post("/csv", response_model=ExportOut, status_code=201)
def create_csv(body: ExportIn, ctx: Ctx = Depends(require("exports:create"))):
    params = body.model_dump(exclude={"export_type"})
    rec, _ = export_service.create_export(ctx.db, ctx.org.id, ctx.user.id, body.export_type, params)
    ctx.db.commit()
    return _out(rec)


@router.get("", response_model=list[ExportOut])
def list_exports(ctx: Ctx = Depends(require("exports:read"))):
    rows = ctx.db.scalars(select(ExportRecord).where(ExportRecord.organization_id == ctx.org.id).order_by(ExportRecord.created_at.desc()).limit(100))
    return [_out(e) for e in rows]


def _get(ctx: Ctx, export_id: str) -> ExportRecord:
    e = ctx.db.scalar(select(ExportRecord).where(ExportRecord.id == export_id, ExportRecord.organization_id == ctx.org.id))
    if not e:
        raise AppError("EXPORT_NOT_FOUND", "Export not found.", 404)
    return e


@router.get("/templates")
def templates(ctx: Ctx = Depends(require("exports:read"))):
    return {"export_types": {k: v["columns"] for k, v in export_service.EXPORTS.items()},
            "templates": export_service.TEMPLATES}


@router.get("/{export_id}", response_model=ExportOut)
def get_export(export_id: str, ctx: Ctx = Depends(require("exports:read"))):
    return _out(_get(ctx, export_id))


@router.get("/{export_id}/download")
def download(export_id: str, ctx: Ctx = Depends(require("exports:read"))):
    e = _get(ctx, export_id)
    return FileResponse(get_storage().path(e.storage_key), media_type="text/csv", filename=f"{e.export_type}-{e.created_at:%Y%m%d}.csv",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
