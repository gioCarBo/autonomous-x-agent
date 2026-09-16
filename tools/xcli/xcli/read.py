"""Read verbs: status, notifications, thread, profile, sweep, analytics, replies.

Reads never change state on X. On failure they exit 1 without filing a bug
issue (a failed read costs information, not state); --issue can force one.
"""

import json
import re
import time

from . import envelope, failure, session
from .cdp import CdpError


def _status_id(url: str) -> str | None:
    m = re.search(r"/status/(\d+)", url or "")
    return m.group(1) if m else None


def _parse_count(s: str | None) -> int | None:
    """'1,234' -> 1234; '1,2K' -> 1200; '3,4M' -> 3400000.

    Rule: with a K/M suffix the last separator is a decimal point; without
    one, separators are thousands grouping. (X mixes locales.)
    """
    if not s:
        return None
    s = s.strip().replace("\u00a0", "")
    mult = 1
    if s and s[-1] in "KkMm":
        mult = 1000 if s[-1] in "Kk" else 1000000
        s = s[:-1]
    if mult > 1 and ("." in s or "," in s):
        # decimal: keep the last separator as '.', drop any others
        head, sep, tail = s.replace(".", ",").rpartition(",")
        s = (head.replace(",", "") + "." + tail) if sep else s
    else:
        s = s.replace(".", "").replace(",", "")
    s = s.strip()
    try:
        return int(float(s) * mult)
    except ValueError:
        return None


def _tweet_core(item_js: str) -> dict:
    """JS side already extracted; here only for shape documentation."""
    return json.loads(item_js)


EXTRACT_STATUS = r"""((wantId) => {
  const arts = [...document.querySelectorAll('[data-testid="tweet"]')];
  if (!arts.length) return null;
  // focal = article whose status link matches the requested id, else first
  const canon = href => (href.match(/\/[A-Za-z0-9_]{1,15}\/status\/\d+/) || [null])[0];
  const focal = wantId
    ? (arts.find(a => [...a.querySelectorAll('a[href*="/status/"]')]
        .some(l => (l.getAttribute('href').match(/\/status\/\d+/) || [''])[0] === '/status/' + wantId)) || arts[0])
    : arts[0];
  const focal_link = focal.querySelector('a[href*="/status/"]');
  const focal_url = focal_link ? ('https://x.com' + canon(focal_link.getAttribute('href'))) : null;
  const txt = focal.querySelector('[data-testid="tweetText"]');
  const time = focal.querySelector('time');
  const user = focal.querySelector('a[href^="/"] span');
  const grp = focal.querySelector('div[role="group"]');
  const num = el => {
    const c = el.querySelector('[data-testid="app-text-transition-container"]');
    return c ? c.textContent.trim() : ((el.textContent || '').match(/[\d.,]+[KkMm]?/) || [null])[0];
  };
  let replies = null, reposts = null, likes = null;
  if (grp) {
    for (const b of grp.querySelectorAll('[data-testid="reply"],[data-testid="retweet"],[data-testid="like"]')) {
      const v = num(b);
      const t = b.getAttribute('data-testid');
      if (t === 'reply') replies = v;
      else if (t === 'retweet') reposts = v;
      else if (t === 'like') likes = v;
    }
  }
  let views = null;
  for (const c of focal.querySelectorAll('[data-testid="app-text-transition-container"]')) {
    if (!grp || !grp.contains(c)) { views = c.textContent.trim(); break; }
  }
  return JSON.stringify({url: focal_url,
    text: txt ? txt.innerText : null,
    time: time ? time.getAttribute('datetime') : null,
    author: user ? user.textContent : null,
    metrics: {replies, reposts, likes, views}});
})"""


def _read_status(cdp, url: str) -> dict | None:
    """Navigate and extract one post; None when no article rendered."""
    cdp.goto(url, settle=4.0)
    raw = cdp.evaluate(f"({EXTRACT_STATUS})({json.dumps(_status_id(url))})")
    if not raw:
        return None
    d = json.loads(raw)
    m = d.get("metrics") or {}
    for k in ("replies", "reposts", "likes", "views"):
        m[k] = _parse_count(m.get(k))
    d["requested_url"] = url
    return d


def status(urls: list[str] | str, cdp=None) -> None:
    """One URL keeps the historical envelope (the post itself, or a bug
    failure). Several URLs — the per-wake readout of our own posts used to
    cost one tab and one LLM turn each — share the tab and come back as
    `items`, a missing article recorded per row instead of failing all."""
    urls = [urls] if isinstance(urls, str) else list(urls)
    own_tab = cdp is None
    cdp = cdp or session.open_tab(urls[0], "status")
    try:
        session.assert_owner_session(cdp, "status")
        if len(urls) == 1:
            d = _read_status(cdp, urls[0])
            if d is None:
                data = failure.save_screenshot(cdp, "status:article-not-found")
                envelope.fail("status", envelope.BUG, "article-not-found",
                              f"no tweet article rendered at {urls[0]}",
                              diagnostics={"url": urls[0]}, screenshot=data)
            envelope.emit("status", d)
            return
        items = []
        for url in urls:
            d = _read_status(cdp, url)
            items.append(d if d is not None
                         else {"requested_url": url, "error": "article-not-found"})
        envelope.emit("status", {"n": len(items), "items": items})
    finally:
        if own_tab:
            cdp.close()


EXTRACT_NOTIFICATIONS = r"""(() => {
  const cells = document.querySelectorAll('[data-testid="cellInnerDiv"]');
  const out = [];
  for (const c of cells) {
    if (!c.querySelector('[data-testid="notification"]') &&
        !c.querySelector('a[href*="/status/"]')) continue;
    const actors = [...c.querySelectorAll('a[href^="/"]')]
      .map(a => (a.getAttribute('href').match(/^\/[A-Za-z0-9_]{1,15}/) || [''])[0])
      .filter(h => h.length > 2);
    const txt = c.querySelector('[data-testid="tweetText"]');
    const time = c.querySelector('time');
    const link = c.querySelector('a[href*="/status/"]');
    // Like/follow/repost cells carry a sentence ("A X piace il tuo post");
    // a reply or mention is rendered as a tweet cell with no such sentence.
    // The first innerText line is the actor's display name (10:01 09-06
    // live read), so take the whole cell minus the embedded post text.
    const notif = c.querySelector('[data-testid="notification"]');
    let header = null;
    if (notif) {
      const clone = notif.cloneNode(true);
      clone.querySelectorAll('[data-testid="tweetText"]').forEach(e => e.remove());
      header = (clone.textContent || '').replace(/\s+/g, ' ').trim() || null;
    }
    out.push({actors: [...new Set(actors)].slice(0, 4),
      text: txt ? txt.innerText.slice(0, 200) : null,
      time: time ? time.getAttribute('datetime') : null,
      post_url: link ? 'https://x.com' + ((link.getAttribute('href').match(/\/[A-Za-z0-9_]{1,15}\/status\/\d+/) || [''])[0]) : null,
      header: header ? header.slice(0, 160) : null,
      is_tweet: !!c.querySelector('[data-testid="tweet"]')});
  }
  return JSON.stringify({n: out.length, items: out});
})()"""

_KIND_PATTERNS = (
    ("like", re.compile(r"piace|liked|like[ds]? your|j'aime|gef[äa]llt", re.I)),
    ("follow", re.compile(r"segu|follow|abonn|folgt", re.I)),
    ("repost", re.compile(r"repost|ripubblic|retweet|republi", re.I)),
)


def notification_kind(row: dict) -> str:
    """Classify a notification row from the header line X renders above
    non-tweet cells; the account's UI language is Italian, so the patterns
    cover it and English. A tweet cell (a reply, a mention, a quote) is a
    potential conversation: `reply`. Anything else is `other` — never a
    silent guess, so the wake still reads it by shape."""
    header = row.get("header") or ""
    for kind, rx in _KIND_PATTERNS:
        if rx.search(header):
            return kind
    if row.get("is_tweet") or row.get("post_url"):
        return "reply"
    return "other"


def _scroll(cdp, times: int = 6, pause: float = 1.0) -> None:
    """Virtualized lists render only what is near the viewport."""
    for _ in range(times):
        cdp.evaluate("window.scrollBy(0, 1400)")
        time.sleep(pause)


def _row_key(item: dict) -> str:
    """Identity for a row the extractor gave no URL — most of the
    notifications feed (18 of 20 rows on 09-05 22:00). The fallback used to
    be positional, so a row the virtualized list re-served on a later scroll
    round minted a fresh key and was collected twice; that feed returned 20
    rows carrying 18 distinct notifications."""
    return json.dumps(item, sort_keys=True, ensure_ascii=False)


def _scroll_collect(cdp, extract_js: str, rounds: int, pause: float,
                    url_key: str = "url",
                    limit: int | None = None) -> list[dict]:
    """extract_js must evaluate to a JSON array. Extract after each scroll
    step and merge: virtualization unmounts off-screen rows, so a single
    end-of-scroll pass loses everything. With `limit`, stop as soon as that
    many distinct rows are in hand — scrolling on for rows the caller will
    discard only costs wall-clock."""
    seen, items = set(), []
    for _ in range(rounds):
        raw = cdp.evaluate(extract_js)
        batch = raw if isinstance(raw, list) else (json.loads(raw) if raw else [])
        for item in batch:
            key = item.get(url_key) or _row_key(item)
            if key not in seen:
                seen.add(key)
                items.append(item)
        if limit is not None and len(items) >= limit:
            break
        cdp.evaluate("window.scrollBy(0, 1400)")
        time.sleep(pause)
    return items[:limit] if limit is not None else items


def notifications(limit: int = 20, cdp=None) -> None:
    own_tab = cdp is None
    cdp = cdp or session.open_tab("about:blank", "notifications")
    try:
        session.assert_owner_session(cdp, "notifications")
        cdp.goto("https://x.com/notifications", settle=5.0)
        items = _scroll_collect(
            cdp, f"JSON.parse({EXTRACT_NOTIFICATIONS}).items",
            rounds=3, pause=1.2, url_key="post_url", limit=limit)
        for it in items:
            it["kind"] = notification_kind(it)
        envelope.emit("notifications", {"n": len(items), "items": items})
    finally:
        if own_tab:
            cdp.close()


EXTRACT_PROFILE = r"""(() => {
  const h = location.pathname.split('/')[1];
  const bio = document.querySelector('[data-testid="UserDescription"]');
  const nameEl = document.querySelector('[data-testid="UserName"] div span');
  const counts = {};
  for (const a of document.querySelectorAll('a[href$="/followers"], a[href$="/following"], a[href$="/verified_followers"]')) {
    const kind = (a.getAttribute('href').match(/\/(followers|following|verified_followers)$/) || [])[1];
    if (!kind || counts[kind]) continue;
    const m = (a.textContent || '').match(/[\d.,]+\s*[KkMm]?/);
    if (m) counts[kind] = m[0].trim();
  }
  const items = [...document.querySelectorAll('[data-testid="cellInnerDiv"]')]
    .slice(0, 20).map(c => {
      const txt = c.querySelector('[data-testid="tweetText"]');
      const time = c.querySelector('time');
      const link = c.querySelector('a[href*="/status/"]');
      return {text: txt ? txt.innerText.slice(0, 280) : null,
        time: time ? time.getAttribute('datetime') : null,
        url: link ? 'https://x.com' + (link.getAttribute('href').match(/\/[A-Za-z0-9_]{1,15}\/status\/\d+/) || [''])[0] : null};
    }).filter(i => i.url);
  return JSON.stringify({handle: h, name: nameEl ? nameEl.textContent : null,
    bio: bio ? bio.innerText : null, counts,
    timeline_rendered: items.length > 0, items});
})()"""


def _read_profile(cdp, handle: str, rounds: int = 4) -> dict:
    cdp.goto(f"https://x.com/{handle}", settle=4.0)
    items = _scroll_collect(
        cdp, f"JSON.parse({EXTRACT_PROFILE}).items",
        rounds=rounds, pause=1.2)
    cdp.evaluate("window.scrollTo(0, 0)")
    time.sleep(1.5)
    header = cdp.evaluate(EXTRACT_PROFILE)
    d = json.loads(header) if header else {"handle": handle}
    counts = d.get("counts") or {}
    # X links the follower count as /verified_followers on most profiles now
    # (all 18 targets on 09-06); readers keyed on `followers` saw None and
    # called it a stub. Same number, keep both keys.
    if "followers" not in counts and "verified_followers" in counts:
        counts["followers"] = counts["verified_followers"]
    d["counts"] = counts
    d["items"] = items
    d["timeline_rendered"] = len(items) > 0
    return d


def profile(handle: str, cdp=None) -> None:
    own_tab = cdp is None
    cdp = cdp or session.open_tab(f"https://x.com/{handle}", "profile")
    try:
        session.assert_owner_session(cdp, "profile")
        envelope.emit("profile", _read_profile(cdp, handle))
    finally:
        if own_tab:
            cdp.close()


TWITTER_EPOCH_MS = 1288834974657


def snowflake_ms(status_id: str | int | None) -> int | None:
    """Post creation time from the ID — the ground truth when X serves a
    scrambled <time> (both `x thread` and `x status` did, 09-05)."""
    try:
        return (int(status_id) >> 22) + TWITTER_EPOCH_MS
    except (TypeError, ValueError):
        return None


def sweep(handles: list[str], since_min: int = 180, pace: float = 10.0,
          rounds: int = 2, cdp=None, now_ms: int | None = None) -> None:
    """The observation sweep as one verb: every target, one tab, and only
    what a fresh-gate can use — posts younger than `since_min` with their
    age decoded from the ID and 80 chars of text. Replaces 5-16 `x profile`
    calls of 20 x 280-char items each. `pace` is the floor on seconds
    between navigations (dense navigation makes X serve empty shells).
    One handle failing never sinks the sweep: it lands in `errors`."""
    own_tab = cdp is None
    cdp = cdp or session.open_tab("about:blank", "sweep")
    try:
        session.assert_owner_session(cdp, "sweep")
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        out, errors, last_nav = [], [], None
        for handle in handles:
            if last_nav is not None:
                wait = pace - (time.monotonic() - last_nav)
                if wait > 0:
                    time.sleep(wait)
            last_nav = time.monotonic()
            try:
                d = _read_profile(cdp, handle, rounds=rounds)
            except CdpError as e:
                errors.append({"handle": handle, "error": f"{type(e).__name__}: {e}"})
                continue
            fresh = []
            for it in d.get("items") or []:
                ms = snowflake_ms(_status_id(it.get("url") or ""))
                if ms is None:
                    continue
                age = (now - ms) / 60000
                if 0 <= age <= since_min:
                    fresh.append({"url": it["url"], "age_min": int(age),
                                  "time": it.get("time"),
                                  "text": (it.get("text") or "")[:80]})
            fresh.sort(key=lambda f: f["age_min"])
            out.append({"handle": d.get("handle") or handle,
                        "counts": d.get("counts") or {},
                        "timeline_rendered": d.get("timeline_rendered", False),
                        "fresh": fresh})
        envelope.emit("sweep", {"since_min": since_min, "n_fresh": sum(len(h["fresh"]) for h in out),
                                "handles": out, "errors": errors})
    finally:
        if own_tab:
            cdp.close()


EXTRACT_THREAD_REPLIES = r"""(() => {
  const arts = [...document.querySelectorAll('[data-testid="tweet"]')];
  const out = [];
  for (const a of arts.slice(0, 40)) {
    const link = a.querySelector('a[href*="/status/"]');
    const txt = a.querySelector('[data-testid="tweetText"]');
    const time = a.querySelector('time');
    const user = a.querySelector('a[href^="/"] span');
    out.push({url: link ? 'https://x.com' + (link.getAttribute('href').match(/\/[A-Za-z0-9_]{1,15}\/status\/\d+/) || [''])[0] : null,
      text: txt ? txt.innerText.slice(0, 400) : null,
      time: time ? time.getAttribute('datetime') : null,
      author: user ? user.textContent : null});
  }
  return JSON.stringify({n: out.length, items: out.filter(i => i.url)});
})()"""


def thread(url: str, cdp=None) -> None:
    own_tab = cdp is None
    cdp = cdp or session.open_tab(url, "thread")
    try:
        session.assert_owner_session(cdp, "thread")
        cdp.goto(url, settle=4.0)
        raw = cdp.evaluate(f"({EXTRACT_STATUS})({json.dumps(_status_id(url))})")
        if not raw:
            data = failure.save_screenshot(cdp, "thread:focal-missing")
            envelope.fail("thread", envelope.BUG, "focal-missing",
                          f"focal tweet did not render at {url}",
                          diagnostics={"url": url}, screenshot=data)
        items = _scroll_collect(
            cdp, f"JSON.parse({EXTRACT_THREAD_REPLIES}).items",
            rounds=6, pause=1.0)
        d = json.loads(raw)
        m = d.get("metrics") or {}
        for k in ("replies", "reposts", "likes", "views"):
            m[k] = _parse_count(m.get(k))
        focal_replies = m.get("replies") or 0
        d["metrics"] = m
        d["replies"] = {"n": len(items), "items": items}
        # X systematically serves reply-less thread pages to limited accounts
        d["degraded"] = bool(focal_replies > 5 and len(items) < 3)
        envelope.emit("thread", d)
    finally:
        if own_tab:
            cdp.close()


# --- analytics -----------------------------------------------------------------

EXTRACT_ANALYTICS = r"""(() => {
  // Premium "Post analytics" modal (x.com/<h>/status/<id>/analytics): a grid
  // of stat blocks, each a muted label div followed by a sibling holding the
  // number in an app-text-transition-container. Labels follow the UI locale
  // (Italian on this account), so the mapping lives in Python.
  const dlg = [...document.querySelectorAll('div[role="dialog"]')]
    .find(d => d.querySelector('[data-testid="app-text-transition-container"]')
               && d.querySelector('[data-testid="tweetText"]'));
  if (!dlg) return null;
  const out = {};
  for (const lab of dlg.querySelectorAll('div[dir="ltr"]')) {
    const t = (lab.textContent || '').trim();
    if (!t || /^[\d.,\s]+[KkMm]?$/.test(t) || t.length > 40) continue;
    const block = lab.parentElement && lab.parentElement.parentElement;
    if (!block) continue;
    const num = block.querySelector('[data-testid="app-text-transition-container"]');
    if (!num || !block.contains(lab)) continue;
    const v = (num.textContent || '').trim();
    if (/^[\d.,\s]+[KkMm]?$/.test(v) && !(t in out)) out[t] = v;
  }
  const link = dlg.querySelector('a[href*="/status/"]');
  return JSON.stringify({url: link ? 'https://x.com' + ((link.getAttribute('href').match(/\/[A-Za-z0-9_]{1,15}\/status\/\d+/) || [''])[0]) : null,
                         raw: out});
})()"""

_ANALYTICS_LABELS = (
    ("impressions", re.compile(r"^(visualizzazioni|impressions?|impressioni)$", re.I)),
    ("engagements", re.compile(r"^(interazioni|engagements?|interactions?)$", re.I)),
    ("detail_expands", re.compile(r"^(espansioni dettagli|detail expands?)$", re.I)),
    ("profile_visits", re.compile(r"^(visite al profilo|profile visits?)$", re.I)),
    ("new_follows", re.compile(r"^(nuovi follower|new follows?|new followers?)$", re.I)),
    ("link_clicks", re.compile(r"^(clic sul link|link clicks?)$", re.I)),
    ("likes", re.compile(r"^(mi piace|likes?)$", re.I)),
    ("replies", re.compile(r"^(risposte|replies|repl(y|ies))$", re.I)),
    ("reposts", re.compile(r"^(repost|reposts|retweets?|ripubblicazioni)$", re.I)),
    ("bookmarks", re.compile(r"^(segnalibri|bookmarks?)$", re.I)),
    ("media_views", re.compile(r"^(visualizzazioni (dei )?media|media views?)$", re.I)),
)


def analytics_fields(raw: dict) -> dict:
    """Map the modal's localized labels to stable keys; unknown labels are
    kept under `other` so a new metric X adds is visible, never lost."""
    out: dict = {}
    other: dict = {}
    for label, value in (raw or {}).items():
        n = _parse_count(value)
        for key, rx in _ANALYTICS_LABELS:
            if rx.match(label.strip()):
                out.setdefault(key, n)
                break
        else:
            other[label] = n
    if other:
        out["other"] = other
    return out


def _read_analytics(cdp, url: str) -> dict | None:
    sid = _status_id(url)
    if not sid:
        return None
    m = re.match(r"https?://(?:www\.)?x\.com/([A-Za-z0-9_]{1,15})/status/", url)
    handle = m.group(1) if m and m.group(1) != "i" else session.OWNER_HANDLE
    cdp.goto(f"https://x.com/{handle}/status/{sid}/analytics", settle=5.0)
    raw = None
    for _ in range(3):  # the grid mounts after the dialog
        raw = cdp.evaluate(EXTRACT_ANALYTICS)
        if raw and json.loads(raw).get("raw"):
            break
        time.sleep(2.0)
    if not raw:
        return None
    d = json.loads(raw)
    fields = analytics_fields(d.get("raw") or {})
    if not fields:
        return None
    return {"requested_url": url, "url": d.get("url") or url,
            "status_id": sid, "analytics": fields}


def analytics(urls: list[str], cdp=None) -> None:
    """Premium per-post analytics for OUR posts: impressions, engagements,
    detail expands, profile visits (the closest thing X exposes to
    follower attribution per post). Several URLs share one tab; a post
    whose modal never renders is one row with `error`, not a failed verb."""
    own_tab = cdp is None
    cdp = cdp or session.open_tab("about:blank", "analytics")
    try:
        session.assert_owner_session(cdp, "analytics")
        items = []
        for url in urls:
            try:
                d = _read_analytics(cdp, url)
            except CdpError as e:
                d = None
                envelope.log(f"analytics {url}: {type(e).__name__}: {e}")
            items.append(d if d is not None
                         else {"requested_url": url, "error": "analytics-not-rendered"})
        envelope.emit("analytics", {"n": len(items), "items": items})
    finally:
        if own_tab:
            cdp.close()


# --- replies (target vetting) ------------------------------------------------------

EXTRACT_WITH_REPLIES = r"""(() => {
  const out = [];
  for (const c of document.querySelectorAll('[data-testid="cellInnerDiv"]')) {
    for (const a of c.querySelectorAll('article')) {
      const link = a.querySelector('a[href*="/status/"]');
      const user = a.querySelector('[data-testid="User-Name"] a[href^="/"]');
      const ctx = [...a.querySelectorAll('div[dir="ltr"]')].map(e => (e.textContent || '').trim())
        .find(t => /^(in risposta a|replying to)/i.test(t));
      out.push({url: link ? 'https://x.com' + ((link.getAttribute('href').match(/\/[A-Za-z0-9_]{1,15}\/status\/\d+/) || [''])[0]) : null,
                author: user ? user.getAttribute('href').replace(/^\//, '') : null,
                ctx: ctx ? ctx.slice(0, 120) : null});
    }
  }
  return JSON.stringify(out.filter(i => i.url));
})()"""


def reply_activity(rows: list[dict], handle: str, now_ms: int, days: int = 7) -> dict:
    """From the with_replies timeline (conversation pairs: a stranger's post
    followed by the handle's answer, or a lone answer carrying "Replying to
    @x"): how many answers to *other* accounts in the last `days`, and to
    how many distinct accounts. Pure."""
    h = handle.lower()
    horizon = now_ms - days * 86400000
    replied_to: dict[str, int] = {}
    prev_author = None
    for row in rows:
        author = (row.get("author") or "").lower()
        ms = snowflake_ms(_status_id(row.get("url") or ""))
        if author == h and ms is not None and ms >= horizon:
            target = None
            ctx = row.get("ctx") or ""
            m = re.findall(r"@([A-Za-z0-9_]{1,15})", ctx)
            others = [x for x in m if x.lower() != h]
            if others:
                target = others[0].lower()
            elif prev_author and prev_author != h:
                target = prev_author
            if target:
                replied_to[target] = replied_to.get(target, 0) + 1
        prev_author = author or prev_author
    return {"handle": handle, "days": days, "replies_to_others": sum(replied_to.values()),
            "distinct_accounts": len(replied_to), "rows": len(rows)}


def replies(handle: str, cdp=None, rounds: int = 4, now_ms: int | None = None) -> None:
    own_tab = cdp is None
    cdp = cdp or session.open_tab("about:blank", "replies")
    try:
        session.assert_owner_session(cdp, "replies")
        cdp.goto(f"https://x.com/{handle}/with_replies", settle=4.0)
        rows = _scroll_collect(cdp, f"JSON.parse({EXTRACT_WITH_REPLIES})", rounds=rounds, pause=1.2)
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        envelope.emit("replies", reply_activity(rows, handle, now))
    finally:
        if own_tab:
            cdp.close()
