"""Dev/verification CLI — the backend is testable before any UI (doc §17.1).

    python cli.py validate-keys
    python cli.py fetch SPY 2026-06-15
    python cli.py backfill [--days 30]
    python cli.py days SPY
    python cli.py find-days SPY --kind gap --top 10
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from app import db
from app.config import load_app_config, load_creds, migrate_legacy_env
from app.marketdata import store
from app.marketdata.calendar import MarketCalendar
from app.marketdata.fetcher import Fetcher
from app.providers.alpaca import AlpacaProvider


def _context():
    migrate_legacy_env()
    cfg = load_app_config()
    conn = db.init_db(cfg.db_path)
    creds = load_creds()
    if creds is None:
        sys.exit(
            "No Alpaca keys found. Run the app once and enter keys, or put "
            "APCA_API_KEY_ID / APCA_API_SECRET_KEY in .env under "
            "%LOCALAPPDATA%\\trading-trainer (free paper signup: alpaca.markets)."
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


def cmd_find_days(args) -> None:
    """Shortlist candidate lesson demo days from daily-bar heuristics —
    a human still eyeballs the chart before a date ships in a lesson."""
    from datetime import timedelta

    from app.models import ET, utcnow

    _, _, provider, calendar, _ = _context()
    symbol = args.symbol.upper()
    today = utcnow().astimezone(ET).date()
    calendar.ensure_around(today)
    target = calendar.latest_on_or_before(today).day
    rows = provider.get_bars_daily([symbol], target - timedelta(days=550), target)[symbol]
    if len(rows) < 30:
        sys.exit(f"not enough daily history for {symbol}")

    scored = []
    for prev, cur in zip(rows, rows[1:]):
        if prev.close <= 0 or cur.high == cur.low:
            continue
        gap_pct = (cur.open / prev.close - 1.0) * 100
        range_pct = (cur.high - cur.low) / prev.close * 100
        trend = abs(cur.close - cur.open) / (cur.high - cur.low)  # 1 = closed on extreme
        scored.append((cur.day, gap_pct, range_pct, trend))

    kind = args.kind
    if kind == "gap":
        scored.sort(key=lambda r: abs(r[1]), reverse=True)
    elif kind == "trend":
        scored = [r for r in scored if r[3] >= 0.65]
        scored.sort(key=lambda r: r[2], reverse=True)
    else:  # quiet — clean canvases for the basics modules
        scored = [r for r in scored if abs(r[1]) < 0.5]
        scored.sort(key=lambda r: abs(r[2] - 1.0))

    print(f"{symbol} — top {args.top} '{kind}' candidates (eyeball before shipping):")
    print(f"{'date':<12}{'gap%':>8}{'range%':>9}{'trend':>7}")
    for day, gap_pct, range_pct, trend in scored[: args.top]:
        print(f"{day.isoformat():<12}{gap_pct:>8.2f}{range_pct:>9.2f}{trend:>7.2f}")


def cmd_scan(args) -> None:
    """Batch detectors over a cached day — sources 'textbook' lesson dates."""
    from app.config import load_rules_config
    from app.detectors.engine import scan_day

    _, conn, _, calendar, fetcher = _context()
    symbol = args.symbol.upper()
    day = date.fromisoformat(args.date)
    fetcher.ensure_day(symbol, day)
    signals = scan_day(conn, calendar, symbol, day, load_rules_config())
    if not signals:
        print(f"{symbol} {day}: no signals fired")
        return
    print(f"{symbol} {day}: {len(signals)} signals")
    for s in signals:
        parts = [f"{s.ts.astimezone().strftime('%H:%M')}", s.setup_type, s.direction]
        if s.entry is not None:
            parts.append(f"entry {s.entry} stop {s.stop} target {s.target} (R:R {s.rr})")
        if s.context:
            parts.append(str(s.context))
        print("  " + "  ".join(parts))


def cmd_fake_live(args) -> None:
    """Drive the REAL poller machinery over a cached day with a fake wall
    clock — a dev rig for testing Market Day outside market hours (doc §17.7),
    not a product feature."""
    from datetime import timedelta

    from app.config import load_app_config, load_rules_config
    from app.lessons.loader import load_lessons
    from app.main import LESSONS_DIR
    from app.marketday.poller import MarketDayPoller

    cfg = load_app_config()
    conn = db.init_db(cfg.db_path)
    day = date.fromisoformat(args.date)
    calendar = MarketCalendar(conn)
    cal_day = calendar.day(day)
    if cal_day is None:
        sys.exit(f"{day} is not a (cached) trading day — fetch it first")
    lessons = load_lessons(LESSONS_DIR)
    wall = {"now": cal_day.session_open_utc() + timedelta(minutes=15)}
    poller = MarketDayPoller(
        cfg=cfg,
        rules_cfg=load_rules_config(),
        provider_fn=lambda: None,  # cache only — the whole point of the rig
        lessons_fn=lambda: lessons,
        now_fn=lambda: wall["now"],
    )
    end = cal_day.session_close_utc() + timedelta(minutes=16)
    ticks = 0
    while wall["now"] < end:
        summary = poller.tick_once()
        ticks += 1
        if summary.get("events"):
            print(f"[{wall['now']:%H:%M}Z] {summary}")
        wall["now"] += timedelta(minutes=args.speed)
    print(f"\n{ticks} ticks. Callouts fired:")
    if poller.callouts:
        clock = poller.session.clock.now() if poller.session else wall["now"]
        for c in poller.callouts.visible(clock):
            if c.get("locked"):
                print(f"  [locked] {c['symbol']} at {c['fired_ts']} -> module {c['unlock_module']}")
            else:
                print(
                    f"  {c['symbol']} {c['setup_type']} {c['direction']} "
                    f"grade={c['grade']['tier'] if c['grade'] else '-'} "
                    f"status={c['status']} outcome={c['outcome']} ({c['outcome_r']}R)"
                )


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
    fd = sub.add_parser("find-days")
    fd.add_argument("symbol")
    fd.add_argument("--kind", choices=["gap", "trend", "quiet"], default="gap")
    fd.add_argument("--top", type=int, default=10)
    fd.set_defaults(fn=cmd_find_days)
    sc = sub.add_parser("scan")
    sc.add_argument("symbol")
    sc.add_argument("date", help="YYYY-MM-DD (a cached trading day)")
    sc.set_defaults(fn=cmd_scan)
    fl = sub.add_parser("fake-live")
    fl.add_argument("date", help="YYYY-MM-DD (a cached trading day)")
    fl.add_argument("--speed", type=int, default=60, help="fake minutes per tick")
    fl.set_defaults(fn=cmd_fake_live)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
