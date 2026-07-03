"""Configuration loading: YAML app config + .env credentials (doc §14).

Config is human-edited YAML re-read on restart; the only mutable piece is the
Alpaca key pair, which the first-run flow writes to .env at the project root.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
ENV_PATH = PROJECT_ROOT / ".env"

KEY_ID_VAR = "APCA_API_KEY_ID"
SECRET_VAR = "APCA_API_SECRET_KEY"


@dataclass(frozen=True)
class AlpacaCreds:
    key_id: str
    secret: str


@dataclass
class AppConfig:
    watchlist: list[str]
    starting_balance: float
    intraday_leverage: float
    default_risk_pct: float
    backfill_days: int
    rvol_baseline_days: int
    poll_interval_seconds: int
    db_path: Path
    allow_untrained_trading: bool


def default_db_path() -> Path:
    # Outside OneDrive on purpose: SQLite WAL + cloud sync corrupts databases.
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "trading-trainer" / "trainer.db"


def load_app_config(path: Path | None = None) -> AppConfig:
    path = path or (CONFIG_DIR / "app_config.yaml")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    db = raw.get("db_path")
    return AppConfig(
        watchlist=[str(s).upper() for s in raw.get("watchlist", [])],
        starting_balance=float(raw.get("starting_balance", 30_000.0)),
        intraday_leverage=float(raw.get("intraday_leverage", 4.0)),
        default_risk_pct=float(raw.get("default_risk_pct", 1.0)),
        backfill_days=int(raw.get("backfill_days", 30)),
        rvol_baseline_days=int(raw.get("rvol_baseline_days", 20)),
        poll_interval_seconds=int(raw.get("poll_interval_seconds", 60)),
        db_path=Path(db).expanduser() if db else default_db_path(),
        allow_untrained_trading=bool(raw.get("allow_untrained_trading", False)),
    )


def load_creds(env_path: Path | None = None) -> AlpacaCreds | None:
    """Read the Alpaca key pair from .env (process env wins, for CI/tests)."""
    values: dict[str, str | None] = dict(dotenv_values(env_path or ENV_PATH))
    values.update({k: v for k, v in os.environ.items() if k in (KEY_ID_VAR, SECRET_VAR)})
    key_id, secret = values.get(KEY_ID_VAR), values.get(SECRET_VAR)
    if key_id and secret:
        return AlpacaCreds(key_id=key_id, secret=secret)
    return None


def save_creds(creds: AlpacaCreds, env_path: Path | None = None) -> None:
    path = env_path or ENV_PATH
    path.write_text(f"{KEY_ID_VAR}={creds.key_id}\n{SECRET_VAR}={creds.secret}\n", encoding="utf-8")
