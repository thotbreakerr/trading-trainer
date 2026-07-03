"""Dev/verification CLI — the backend is testable before any UI (doc §17.1).

    python cli.py validate-keys
    python cli.py fetch SPY 2026-06-15
    python cli.py backfill [--days 30]
    python cli.py days SPY
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from app import db
from app.config import load_app_config, load_creds
from app.marketdata import store
from app.marketdata.calendar import MarketCalendar
from app.marketdata.fetcher import Fetcher
from app.providers.alpaca import AlpacaProvider


def _context():
    cfg = load_app_config()
    conn = db.init_db(cfg.db_path)
    creds = load_creds()
    if creds is None:
        sys.exit(
            "No Alpaca keys found. Put APCA_API_KEY_ID / APCA_API_SECRET_KEY in "
            ".env at the project root (free paper-account signup: alpaca.markets)."
        )
    provider = AlpacaProvider(creds.key_id, creds.secret)
    calendar = MarketCalendar(conn, provider)
    fetcher = Fetcher(conn, provider, calendar, rvol_baseline_days=cfg.rvol_baseline_days)
    return cfg, conn, provider, calendar, fetcher


def cmd_validate_keys(_args) -> None:
    _, _, provider, _, _ = _context()
    v = provider.validate_keys()
    print(f"data host    : {'OK' if v.data_ok else 'FAIL'}")
    print(f"trading host : {'OK' if v.trading_ok else 'FAIL'}")
    if v.error:
        print(f"error        : {v.error}")
    sys.exit(0 if v.ok else 1)


def cmd_fetch(args) -> None:
    _, _, _, _, fetcher = _context()
    report = fetcher.ensure_day(args.symbol.upper(), date.fromisoformat(args.date))
    print(f"{report.symbol} {report.requested}:")
    print(f"  1m days fetched : {len(report.fetched_1m_days)} ({report.bars_added} bars)")
    print(f"  daily bars      : {report.daily_bars_added}")
    if report.split_refetched:
        print("  NOTE: split detected — symbol cache was wiped and refetched")
    for w in report.warnings:
        print(f"  warn: {w}")


def cmd_backfill(args) -> None:
    cfg, _, _, _, fetcher = _context()
    days = args.days or cfg.backfill_days
    print(f"Backfilling {len(cfg.watchlist)} symbols × last {days} trading days + today…")

    def on_progress(symbol: str, i: int, total: int) -> None:
        print(f"  [{i + 1}/{total}] {symbol}…", flush=True)

    reports = fetcher.backfill(cfg.watchlist, days, on_progress)
    print(f"Done: {sum(r.bars_added for r in reports)} bars added.")
    for r in reports:
        for w in r.warnings:
            print(f"  warn: {w}")


def cmd_days(args) -> None:
    cfg = load_app_config()
    conn = db.init_db(cfg.db_path)
    calendar = MarketCalendar(conn)  # cached-only view is fine here
    symbol = args.symbol.upper()
    rows = store.list_cached_days(conn, symbol)
    if not rows:
        print(f"No cached days for {symbol}.")
        return
    for day, fetched_at in rows:
        cal = calendar.day(day)
        if cal is not None:
            n = store.count_bars_1m_for_day(
                conn, symbol, cal.session_open_utc(), cal.session_close_utc()
            )
            complete = fetched_at > cal.session_close_utc()
            flag = "complete" if complete else "partial"
        else:
            n, flag = 0, "no-calendar"
        print(f"{day}  {n:5d} bars  {flag}  (fetched {fetched_at:%Y-%m-%d %H:%M}Z)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate-keys").set_defaults(fn=cmd_validate_keys)
    f = sub.add_parser("fetch")
    f.add_argument("symbol")
    f.add_argument("date", help="YYYY-MM-DD (a trading day)")
    f.set_defaults(fn=cmd_fetch)
    b = sub.add_parser("backfill")
    b.add_argument("--days", type=int, default=None)
    b.set_defaults(fn=cmd_backfill)
    d = sub.add_parser("days")
    d.add_argument("symbol")
    d.set_defaults(fn=cmd_days)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
