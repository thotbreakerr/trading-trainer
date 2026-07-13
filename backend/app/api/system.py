"""System endpoints: health, first-run key flow (doc §13, §16.9)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.api import deps
from app.config import AlpacaCreds, save_creds
from app.providers.alpaca import AlpacaProvider

router = APIRouter()


class KeysIn(BaseModel):
    key_id: str
    secret: str


@router.get("/health")
def health(request: Request) -> dict:
    cfg = deps.get_cfg(request)
    deps.get_db(request)  # raises if the DB is unusable
    return {
        "status": "ok",
        "keys_present": deps.get_provider(request) is not None,
        "db_path": str(cfg.db_path),
        "watchlist": cfg.watchlist,
        "features": cfg.feature_flags,
    }


@router.get("/features")
def features(request: Request) -> dict:
    return {"features": deps.get_cfg(request).feature_flags or {}}


@router.get("/keys/status")
def keys_status(request: Request) -> dict:
    return {"present": deps.get_provider(request) is not None}


@router.post("/keys")
def set_keys(body: KeysIn, request: Request) -> dict:
    """Validate against BOTH Alpaca hosts, then persist to .env (doc §13)."""
    candidate = AlpacaProvider(body.key_id.strip(), body.secret.strip())
    result = candidate.validate_keys()
    if not result.ok:
        raise HTTPException(
            status_code=400,
            detail={
                "data_ok": result.data_ok,
                "trading_ok": result.trading_ok,
                "error": result.error,
            },
        )
    save_creds(AlpacaCreds(key_id=body.key_id.strip(), secret=body.secret.strip()))
    request.app.state.provider = candidate
    return {"data_ok": True, "trading_ok": True}
