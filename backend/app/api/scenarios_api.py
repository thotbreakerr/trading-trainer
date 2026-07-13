"""Historical scenario explorer, blind replay, and saved playlists."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import sessions
from app.api import deps
from app.api.sessions_api import _info
from app.models import to_db_ts, utcnow
from app.scenarios import service
from app.sim.engine import SimEngine

router = APIRouter()


@router.get("/scenarios")
def scenarios(
    request: Request,
    setup: str | None = None,
    direction: str | None = None,
    symbol: str | None = None,
    grade: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    blind: bool = True,
    refresh: bool = False,
    limit: int = 30,
) -> dict:
    limit = max(1, min(limit, 100))
    conn = deps.get_db(request)
    indexed = service.build_catalog(
        conn, deps.get_calendar(request), request.app.state.rules,
        deps.get_cfg(request).watchlist, refresh=refresh,
    )
    result = service.list_catalog(
        conn, setup=setup, direction=direction, symbol=symbol, grade=grade,
        date_from=date_from, date_to=date_to, limit=limit, blind=blind,
    )
    result["index"] = indexed
    return result


@router.post("/scenarios/{scenario_id}/session")
def start_scenario(scenario_id: str, request: Request) -> dict:
    conn = deps.get_db(request)
    calendar = deps.get_calendar(request)
    try:
        row = conn.execute("SELECT day FROM scenario_catalog WHERE id = ?", (scenario_id,)).fetchone()
        if row is None:
            raise KeyError(scenario_id)
        day = date.fromisoformat(row["day"])
        cal_day = calendar.day(day)
        if cal_day is None:
            raise ValueError("scenario day is missing from the calendar")
        full, anchor = service.start_at(conn, scenario_id, cal_day.open_utc())
        cfg = deps.get_cfg(request)
        session = sessions.create_session(
            calendar, [full["symbol"]], day, lookback_days=1, start_at=anchor,
            mode="scenario", sim=SimEngine(cfg.starting_balance, cfg.intraday_leverage, mode="scenario"),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="no such scenario")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"scenario_id": scenario_id, "session": _info(session)}


@router.get("/scenarios/{scenario_id}/resolution")
def scenario_resolution(scenario_id: str, request: Request) -> dict:
    try:
        return service.resolution(deps.get_db(request), deps.get_calendar(request), scenario_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such scenario")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


class PlaylistIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.get("/scenario-playlists")
def playlists(request: Request) -> dict:
    conn = deps.get_db(request)
    rows = conn.execute(
        "SELECT p.id, p.name, p.created_at, COUNT(i.scenario_id) AS items "
        "FROM scenario_playlists p LEFT JOIN scenario_playlist_items i ON i.playlist_id = p.id "
        "GROUP BY p.id ORDER BY p.created_at DESC"
    ).fetchall()
    return {"playlists": [dict(row) for row in rows]}


@router.post("/scenario-playlists")
def create_playlist(body: PlaylistIn, request: Request) -> dict:
    now = to_db_ts(utcnow())
    cur = deps.get_db(request).execute(
        "INSERT INTO scenario_playlists (name, created_at) VALUES (?, ?)", (body.name.strip(), now)
    )
    return {"id": cur.lastrowid, "name": body.name.strip(), "created_at": now, "items": 0}


@router.get("/scenario-playlists/{playlist_id}")
def playlist(playlist_id: int, request: Request, blind: bool = True) -> dict:
    conn = deps.get_db(request)
    saved = conn.execute("SELECT * FROM scenario_playlists WHERE id = ?", (playlist_id,)).fetchone()
    if saved is None:
        raise HTTPException(status_code=404, detail="no such playlist")
    rows = conn.execute(
        "SELECT c.* FROM scenario_playlist_items i "
        "JOIN scenario_catalog c ON c.id = i.scenario_id "
        "WHERE i.playlist_id = ? ORDER BY i.position",
        (playlist_id,),
    ).fetchall()
    return {
        "playlist": {**dict(saved), "items": len(rows)},
        "scenarios": [service.catalog_item(row, blind) for row in rows],
    }


@router.post("/scenario-playlists/{playlist_id}/items/{scenario_id}")
def add_playlist_item(playlist_id: int, scenario_id: str, request: Request) -> dict:
    conn = deps.get_db(request)
    if conn.execute("SELECT 1 FROM scenario_playlists WHERE id = ?", (playlist_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="no such playlist")
    if conn.execute("SELECT 1 FROM scenario_catalog WHERE id = ?", (scenario_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="no such scenario")
    position = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM scenario_playlist_items WHERE playlist_id = ?",
        (playlist_id,),
    ).fetchone()[0]
    conn.execute(
        "INSERT OR IGNORE INTO scenario_playlist_items (playlist_id, scenario_id, position) VALUES (?, ?, ?)",
        (playlist_id, scenario_id, position),
    )
    return {"playlist_id": playlist_id, "scenario_id": scenario_id, "position": position}
