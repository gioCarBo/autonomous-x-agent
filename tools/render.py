#!/usr/bin/env python3
"""render.py — the only way an image reaches a post: a template over data.

    render.py metrics [--out renders/metrics-YYYY-MM-DD.png] [--days 14]
    render.py card --title T (--body B | --body-file F) [--kicker K] [--footer F] [--out …]
    render.py scan TEXT…                 the safety gate alone (exit 2 = refused)
    … --html-only                        write the HTML next to --out, skip Chrome

Floor rule (owner, 2026-09-06): images are rendered from templates over
structured data, never raw terminal or browser screenshots; no third-party
content beyond what is public and never the handle of anyone who blocked
us; a secrets scan runs before anything is rasterized. This tool is that
rule made mechanical: every field of every template passes `scan()`, the
PNG is rasterized by the agent Chrome from a local HTML file the tool
wrote, and a `<file>.json` sidecar (sha256 + the data) is written next to
it. `x post|reply|quote --media` accepts only files with such a sidecar.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RENDERS = ROOT / "renders"
STATS = ROOT / "memory" / "stats.json"
ITEMS = ROOT / "memory" / "items.json"
STATE = ROOT / "memory" / "state.json"
W, H = 1200, 675          # X card 16:9
SCALE = 2                 # 2400x1350 px, ~200-400 KB

SECRET_PATTERNS = (
    ("api key", re.compile(r"\b(sk|rk|pk)[-_][A-Za-z0-9_-]{12,}")),
    ("github token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("aws key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{16,}", re.I)),
    ("x cookie", re.compile(r"\b(auth_token|ct0|kdt|twid)\s*[=:]", re.I)),
    ("password", re.compile(r"\b(password|passwd|secret|token)\s*[=:]\s*\S+", re.I)),
    ("local path", re.compile(r"(/home/\w+|/Users/\w+|/tmp/\S+|~/\S+|C:\\\\Users)")),
    ("ip address", re.compile(r"\b\d{1,3}(\.\d{1,3}){3}(:\d+)?\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("cdp endpoint", re.compile(r"\b(BU_CDP_URL|devtools|localhost:\d+)\b", re.I)),
)
PRIVATE = ROOT / "memory" / "private.json"   # git-ignored: {"employer_terms": [...]}


def private_terms() -> list[str]:
    try:
        return [t for t in json.loads(PRIVATE.read_text()).get("employer_terms", []) if t]
    except (OSError, json.JSONDecodeError):
        return []


def blocked_handles(state: dict | None = None) -> set[str]:
    """Handles whose do-not-reply reason records an author block."""
    if state is None:
        try:
            state = json.loads(STATE.read_text())
        except (OSError, json.JSONDecodeError):
            state = {}
    out = set()
    for h, v in (state.get("do_not_reply") or {}).items():
        if str((v or {}).get("reason", "")).upper().startswith("BLOCKED BY AUTHOR"):
            out.add(h.lower())
    return out


def scan(fields: dict, blocked: set[str] | None = None) -> list[str]:
    """Reasons the data must not be rendered; empty = clean. The employer's
    name lives in memory/private.json (git-ignored) so the public code does
    not carry it."""
    blocked = blocked_handles() if blocked is None else blocked
    reasons = []
    terms = [re.compile(r"\b" + re.escape(t) + r"\b", re.I) for t in private_terms()]
    for key, value in fields.items():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        for name, rx in SECRET_PATTERNS:
            if rx.search(text):
                reasons.append(f"{key}: looks like a {name}")
        if any(rx.search(text) for rx in terms):
            reasons.append(f"{key}: names the owner's employer")
        low = text.lower()
        for h in blocked:
            if re.search(r"(^|[^a-z0-9_])@?" + re.escape(h) + r"([^a-z0-9_]|$)", low):
                reasons.append(f"{key}: names a blocking account")
    return reasons


# --- templates ------------------------------------------------------------------------

CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { width: %dpx; height: %dpx; overflow: hidden; background: #0f1419; }
  body { font-family: 'DejaVu Sans', Inter, Helvetica, Arial, sans-serif; color: #e7e9ea; padding: 56px 64px; display: flex; flex-direction: column; }
  .kicker { font-size: 22px; letter-spacing: .08em; text-transform: uppercase; color: #8b98a5; }
  h1 { font-size: 44px; font-weight: 700; line-height: 1.15; margin-top: 14px; }
  .body { font-size: 30px; line-height: 1.4; margin-top: 28px; color: #e7e9ea; white-space: pre-wrap; flex: 1; }
  .footer { display: flex; justify-content: space-between; gap: 32px; font-size: 18px; color: #8b98a5; margin-top: 24px; white-space: nowrap; }
  .big { font-size: 132px; font-weight: 700; line-height: 1; letter-spacing: -.02em; }
  .delta { font-size: 28px; color: #00ba7c; margin-left: 20px; white-space: nowrap; }
  .delta.neg { color: #f4212e; }
  .main { flex: 1; display: grid; grid-template-columns: 1fr 520px; gap: 48px; align-items: center; margin-top: 12px; }
  .hero { display: flex; align-items: baseline; }
  .row { display: flex; gap: 40px; margin-top: 40px; }
  .stat .v { font-size: 38px; font-weight: 700; }
  .stat .l { font-size: 18px; color: #8b98a5; margin-top: 4px; white-space: nowrap; }
  .chart svg { display: block; }
  svg text { font-family: inherit; }
""" % (W, H)


def _page(inner: str) -> str:
    return "<!doctype html><html><head><meta charset='utf-8'><style>%s</style></head><body>%s</body></html>" % (CSS, inner)


def card_html(title: str, body: str, kicker: str = "AI-run account · notes to self",
              footer: str = "written by the AI running @GCBullGlasses · rendered from its own log") -> str:
    return _page(
        "<div class='kicker'>%s</div><h1>%s</h1><div class='body'>%s</div>"
        "<div class='footer'><span>%s</span><span>%s</span></div>" % (
            html.escape(kicker), html.escape(title), html.escape(body),
            html.escape(footer), html.escape(datetime.now().astimezone().strftime("%Y-%m-%d"))))


def _series(stats: dict, days: int) -> list[dict]:
    daily = list(reversed((stats.get("daily") or [])[:days]))
    return [d for d in daily if isinstance(d.get("followers"), int)]


def _polyline(vals: list[int], x0: float, y0: float, w: float, h: float) -> str:
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    step = w / max(len(vals) - 1, 1)
    pts = ["%.1f,%.1f" % (x0 + i * step, y0 + h - (v - lo) / span * h) for i, v in enumerate(vals)]
    return " ".join(pts)


def metrics_html(stats: dict, items: dict, days: int = 14, today: datetime | None = None) -> tuple[str, dict]:
    today = today or datetime.now().astimezone()
    series = _series(stats, days)
    if not series:
        raise ValueError("stats.json has no follower series yet")
    latest, first = series[-1], series[0]
    prev = series[-2] if len(series) > 1 else first
    followers = latest["followers"]
    delta_day = followers - prev["followers"]
    delta_win = followers - first["followers"]
    # the chart ends yesterday: today's row (if any) is a partial day
    hist = [d for d in series if d["date"] < today.date().isoformat()] or series
    views = [int((d.get("totals") or {}).get("views") or 0) for d in hist]
    fol = [d["followers"] for d in hist]
    start = datetime.fromisoformat(series[0]["date"]).date()
    day_n = (today.date() - datetime(2026, 8, 30).date()).days + 1
    # "yesterday" is the calendar day that ended, whether or not a row for
    # today exists yet (the 06:30 reflect may already have recorded one)
    ystr = (today.date().toordinal() - 1)
    yiso = datetime.fromordinal(ystr).date().isoformat()
    yrow = next((d for d in series if d["date"] == yiso), None)
    views_y = int((yrow.get("totals") or {}).get("views") or 0) if yrow else views[-1]
    posted = [it for it in items.get("items", [])
              if datetime.fromisoformat(it["published"]).astimezone().date().toordinal() == ystr]
    originals = len([it for it in posted if it["kind"] != "reply"])
    replies = len([it for it in posted if it["kind"] == "reply"])
    pv = sum(((it["snapshots"] or [{}])[-1].get("profile_visits") or 0) for it in posted)

    cw, ch = 520, 250
    line = _polyline(fol, 0, 0, cw, ch)
    bars = ""
    if views:
        mx = max(views) or 1
        bw = cw / len(views)
        for i, v in enumerate(views):
            bh = v / mx * ch
            bars += "<rect x='%.1f' y='%.1f' width='%.1f' height='%.1f' rx='4' fill='#1d9bf0' opacity='.35'/>" % (
                i * bw + 3, ch - bh, bw - 6, bh)
    svg = ("<svg width='%d' height='%d' viewBox='0 0 %d %d'>%s"
           "<polyline points='%s' fill='none' stroke='#e7e9ea' stroke-width='5' stroke-linejoin='round' stroke-linecap='round'/>"
           "<text x='0' y='%d' fill='#8b98a5' font-size='18'>%s</text>"
           "<text x='%d' y='%d' fill='#8b98a5' font-size='18' text-anchor='end'>%s</text>"
           "</svg>") % (cw, ch + 30, cw, ch + 30, bars, line, ch + 24, hist[0]["date"][5:], cw, ch + 24, hist[-1]["date"][5:])
    inner = (
        "<div class='kicker'>Day %d of an AI running this account · followers</div>"
        "<div class='main'>"
        "<div>"
        "<div class='hero'><span class='big'>%d</span><span class='delta%s'>%+d today · %+d in %d days</span></div>"
        "<div class='row'>"
        "<div class='stat'><div class='v'>%s</div><div class='l'>views yesterday</div></div>"
        "<div class='stat'><div class='v'>%d</div><div class='l'>originals</div></div>"
        "<div class='stat'><div class='v'>%d</div><div class='l'>replies</div></div>"
        "<div class='stat'><div class='v'>%d</div><div class='l'>profile visits</div></div>"
        "</div></div>"
        "<div class='chart'>%s</div>"
        "</div>"
        "<div class='footer'><span>line: followers · bars: daily views · read from X by the agent, not typed by a human</span><span>%s</span></div>"
    ) % (day_n, followers, "" if delta_day >= 0 else " neg", delta_day, delta_win, len(series),
         "{:,}".format(views_y).replace(",", "."), originals, replies, pv, svg, today.strftime("%Y-%m-%d"))
    data = {"day": day_n, "followers": followers, "delta_day": delta_day, "delta_window": delta_win,
            "views_yesterday": views_y, "originals": originals, "replies": replies, "profile_visits": pv,
            "series_from": str(start)}
    return _page(inner), data


# --- rasterize ------------------------------------------------------------------------

def rasterize(html_path: Path, out: Path) -> None:
    """Agent Chrome (CDP) paints the local HTML and screenshots the card."""
    sys.path.insert(0, str(ROOT / "tools" / "xcli"))
    from xcli import session  # noqa: WPS433
    cdp = session.open_tab("about:blank", "render")
    try:
        cdp.command("Emulation.setDeviceMetricsOverride",
                    {"width": W, "height": H, "deviceScaleFactor": 1, "mobile": False}, timeout=15)
        cdp.goto(html_path.resolve().as_uri(), settle=1.2)
        cdp.command("Emulation.setDeviceMetricsOverride",
                    {"width": W, "height": H, "deviceScaleFactor": 1, "mobile": False}, timeout=15)
        time.sleep(0.4)
        res = cdp.command("Page.captureScreenshot",
                          {"format": "png", "captureBeyondViewport": False,
                           "clip": {"x": 0, "y": 0, "width": W, "height": H, "scale": SCALE}}, timeout=30)
    finally:
        cdp.close()
    import base64
    out.write_bytes(base64.b64decode(res["data"]))


def write_sidecar(out: Path, template: str, data: dict) -> dict:
    meta = {"renderer": "tools/render.py", "template": template,
            "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
            "rendered_at": datetime.now().astimezone().isoformat(timespec="minutes"), "data": data}
    Path(str(out) + ".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n")
    return meta


def render(template: str, page: str, data: dict, out: Path, html_only: bool = False) -> Path:
    reasons = scan(data)
    if reasons:
        raise PermissionError("refused: " + "; ".join(reasons))
    RENDERS.mkdir(exist_ok=True)
    out = out if out.is_absolute() else ROOT / out
    html_path = out.with_suffix(".html")
    html_path.write_text(page)
    if html_only:
        return html_path
    try:
        rasterize(html_path, out)
    finally:
        html_path.unlink(missing_ok=True)
    write_sidecar(out, template, data)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="render.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="verb", required=True)
    m = sub.add_parser("metrics", help="the daily followers card")
    m.add_argument("--days", type=int, default=14)
    m.add_argument("--out", type=Path)
    m.add_argument("--html-only", action="store_true")
    c = sub.add_parser("card", help="a text card (postmortem, note)")
    c.add_argument("--title", required=True)
    c.add_argument("--body"); c.add_argument("--body-file")
    c.add_argument("--kicker", default="AI-run account · notes to self")
    c.add_argument("--footer", default="written by the AI running @GCBullGlasses · rendered from its own log")
    c.add_argument("--out", type=Path)
    c.add_argument("--html-only", action="store_true")
    s = sub.add_parser("scan", help="run the safety gate on text")
    s.add_argument("text", nargs="+")
    a = ap.parse_args(argv)
    today = datetime.now().astimezone()
    if a.verb == "scan":
        reasons = scan({"text": " ".join(a.text)})
        print("\n".join(reasons) if reasons else "clean")
        return 2 if reasons else 0
    try:
        if a.verb == "metrics":
            stats = json.loads(STATS.read_text()) if STATS.exists() else {}
            items = json.loads(ITEMS.read_text()) if ITEMS.exists() else {}
            page, data = metrics_html(stats, items, days=a.days, today=today)
            out = a.out or RENDERS / ("metrics-%s.png" % today.strftime("%Y-%m-%d"))
            path = render("metrics", page, data, out, a.html_only)
        else:
            body = Path(a.body_file).read_text() if a.body_file else (a.body or "")
            if not body.strip():
                print("render.py card: --body or --body-file required", file=sys.stderr)
                return 2
            if len(body) > 600 or len(a.title) > 90:
                print("render.py card: title <= 90 chars, body <= 600 chars (it must be readable on a phone)", file=sys.stderr)
                return 2
            data = {"title": a.title, "body": body, "kicker": a.kicker, "footer": a.footer}
            out = a.out or RENDERS / ("card-%s.png" % today.strftime("%Y-%m-%d-%H%M"))
            path = render("card", card_html(a.title, body, a.kicker, a.footer), data, out, a.html_only)
    except PermissionError as e:
        print("render.py: %s" % e, file=sys.stderr)
        return 2
    except ValueError as e:
        print("render.py: %s" % e, file=sys.stderr)
        return 2
    print(str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
