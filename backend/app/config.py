"""Configuration loading: YAML app config + .env credentials (doc §14).

Config is human-edited YAML re-read on restart; the only mutable piece is the
Alpaca key pair, which the first-run flow writes to .env in the local data
directory (outside the OneDrive-synced project folder on purpose).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import dotenv_values

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"


def data_dir() -> Path:
    """Per-user local data dir — secrets and the live WAL database don't
    belong in cloud-synced folders (the project root syncs to OneDrive)."""
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "trading-trainer"


LEGACY_ENV_PATH = PROJECT_ROOT / ".env"  # pre-v1.1 location (synced to OneDrive)
ENV_PATH = data_dir() / ".env"

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
    backup_dir: Path = PROJECT_ROOT / "backups"
    backup_keep: int = 14
    backup_min_interval_hours: float = 12.0


def default_db_path() -> Path:
    # Outside OneDrive on purpose: SQLite WAL + cloud sync corrupts databases.
    return data_dir() / "trainer.db"


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
        # Cold single-file backups ARE safe in OneDrive (unlike the live WAL
        # DB), so the synced project folder is the deliberate default.
        backup_dir=Path(raw["backup_dir"]).expanduser()
        if raw.get("backup_dir")
        else PROJECT_ROOT / "backups",
        backup_keep=int(raw.get("backup_keep", 14)),
        backup_min_interval_hours=float(raw.get("backup_min_interval_hours", 12)),
    )


def load_rules_config(path: Path | None = None) -> dict:
    """Detector thresholds / grader params / unlock map (doc §10, §14)."""
    path = path or (CONFIG_DIR / "rules_config.yaml")
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{KEY_ID_VAR}={creds.key_id}\n{SECRET_VAR}={creds.secret}\n", encoding="utf-8")


def migrate_legacy_env(legacy: Path | None = None, new: Path | None = None) -> str | None:
    """One-time move of .env out of the (OneDrive-synced) project root.

    Returns "moved", "stale-legacy", or None. Never raises — a locked file
    (OneDrive sync in flight) must not stop the app from booting.
    """
    legacy = legacy or LEGACY_ENV_PATH
    new = new or ENV_PATH
    try:
        if not legacy.exists():
            return None
        if new.exists():
            logger.warning(
                "stale legacy .env at %s (using %s) — delete it and consider rotating "
                "the Alpaca key pair: the secret lived in a cloud-synced folder",
                legacy,
                new,
            )
            return "stale-legacy"
        new.parent.mkdir(parents=True, exist_ok=True)
        new.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        legacy.unlink()
        logger.warning(
            ".env moved out of the project folder: %s -> %s — consider rotating the "
            "Alpaca key pair (the old file lived in OneDrive)",
            legacy,
            new,
        )
        return "moved"
    except OSError as e:
        logger.warning(".env migration failed (will retry next start): %s", e)
        return None
