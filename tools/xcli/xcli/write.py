"""Write verbs: reply, post, quote, like, repost, follow, bio, pin.

The recipe lives here (encoded once, per ADR 0001). Composer entry follows
the caret-trap findings of logs/2026-08-31-composer-fix-test.md: NEVER click
directly into a composer on this Chrome build — focus will not land (issue
#11, 6 live failures on 09-03). Proven entry instead:

  reply: trusted click on the focal post's reply button
         ([data-testid="reply"]) -> modal composer AUTO-FOCUSED
         (08-31 Path B, gate-verified; the timestamp+r seed lost focus to
         the timeline container on 09-03 — see wake-1400 log)
  post:  https://x.com/compose/post -> modal composer AUTO-FOCUSED
         (focus-gate verified live 09-03)

Then, both verbs:
  1. focus gate: activeElement is a dialog composer + caret inside
  2. target gate: modal quotes the intended parent (reply only)
  3. insert text at browser level via CDP Input.insertText (fires the
     input events React/Lexical listen to — issue #10)
  4. text gate: dialog editor content must contain the draft
  5. submit gate: dialog tweetButton present and not aria-disabled
  6. submit via trusted click on the button rect
  7. evidence: re-read the published item from the page and match text

check_only runs steps 1-5 without 6-7. Any failed gate = no submit, bug
issue with screenshot.

bio:  https://x.com/settings/profile opens the edit-profile dialog
      (scouted 09-05 07:00). Do NOT click the profile-page "Edit profile"
      button — JS click and trusted click both failed 09-05 06:50.
      Fill textarea[name=description] via the native value setter (this
      is a form textarea, not a Lexical composer). Save via trusted
      click on [data-testid=Profile_Save_Button].

pin:  trusted click on the focal post's caret, then the pin menuitem,
      then the confirm sheet. Same instant-scroll + stable-rect recipe.

like / repost / quote / follow (09-06): trusted click on the focal
      article's [data-testid=like|retweet] button, or the profile's
      [data-testid$=-follow] button; repost and quote go through the
      retweet menu ([data-testid=retweetConfirm] / the "Cita|Quote" item,
      which opens the modal composer). Each verifies the toggled state
      (unlike / unretweet / -unfollow) or the published item.

Caps are the CLI's job (caps.py): every write verb checks the daily
counter before touching the page and consumes it after evidence. Media
(--media) is accepted only from renders/ with a render.py sidecar whose
sha256 matches — a raw screenshot cannot go through this path (Floor).
Every published item is registered in memory/items.json (items.py) so the
scheduler measures it without the LLM.
"""

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from . import caps, envelope, failure, session

ROOT = Path(__file__).resolve().parents[3]
RENDERS = ROOT / "renders"
MEDIA_EXT = {".png", ".jpg", ".jpeg", ".webp"}
MEDIA_MAX_BYTES = 5 * 1024 * 1024
MEDIA_MAX_COUNT = 4

SUBMIT_TIMEOUT = 25.0

DIALOG_FOCUS_JS = """(() => {
  const dialogs = [...document.querySelectorAll('div[role="dialog"]')];
  const editors = dialogs.flatMap(d =>
    [...d.querySelectorAll('[data-testid^="tweetTextarea_"]')]
      .filter(e => e.getAttribute('contenteditable') === 'true'));
  if (!editors.length) return JSON.stringify({ok: false,
    stage: 'no-modal-editor',
    detail: dialogs.length + ' dialog(s), 0 editable composers'});
  const ae = document.activeElement;
  const sel = window.getSelection();
  const anchorOk = !!(sel && sel.anchorNode &&
    editors.some(e => e.contains(sel.anchorNode.parentElement ||
                                 sel.anchorNode)));
  if (!(ae && ae.isContentEditable &&
        editors.some(e => e.contains(ae)) && anchorOk))
    return JSON.stringify({ok: false, stage: 'modal-not-focused',
      detail: 'activeElement=' + (ae ? ae.tagName + '.' +
               (ae.getAttribute('data-testid') || '') : 'null')});
  return JSON.stringify({ok: true, stage: 'focused'});
})()"""

TARGET_JS = """((handle) => {
  const d = [...document.querySelectorAll('div[role="dialog"]')]
    .find(d => d.querySelector('[data-testid^="tweetTextarea_"]'));
  if (!d) {
    // 09-06: a reply-button click on a blocked author opens a notice
    // dialog ("L'autore ti ha bloccato" / "The author has blocked you"),
    // which read as a harness no-modal for two wakes (#17, #18).
    const block = [...document.querySelectorAll('div[role="dialog"]')]
      .find(d => /bloccat|blocked|can.t reply/i.test(d.innerText || ''));
    if (block) return JSON.stringify({ok: false, stage: 'blocked-by-author',
      detail: (block.innerText || '').replace(/\\s+/g, ' ').slice(0, 160)});
    return JSON.stringify({ok: false, stage: 'no-modal',
      detail: 'no dialog with a composer after reply-button click'});
  }
  const ok = d.innerText.toLowerCase().includes(handle.toLowerCase());
  return JSON.stringify({ok, stage: ok ? 'target-ok' : 'wrong-target',
    detail: 'expected parent @' + handle});
})"""

DIALOG_SUBMIT_JS = """(() => {
  const btn = [...document.querySelectorAll('div[role="dialog"]')]
    .flatMap(d => [...d.querySelectorAll('[data-testid="tweetButton"]')])
    .find(b => b);
  if (!btn) return null;
  btn.scrollIntoView({block: 'center', behavior: 'instant'});
  const r = btn.getBoundingClientRect();
  if (!r || !r.width) return null;
  return JSON.stringify({x: r.x + r.width / 2, y: r.y + r.height / 2});
})()"""

REPLY_BUTTON_JS = """((sid) => {
  const focal = [...document.querySelectorAll('article')]
    .find(a => a.querySelector('a[href*="/status/' + sid + '"] time'));
  if (!focal) return null;
  const btn = focal.querySelector('[data-testid="reply"]');
  if (!btn) return null;
  btn.scrollIntoView({block: 'center', behavior: 'instant'});
  const r = btn.getBoundingClientRect();
  if (!r || !r.width) return null;
  return JSON.stringify({x: r.x + r.width / 2, y: r.y + r.height / 2});
})"""

# Permalinks often reach readyState=complete as an empty shell (spinner,
# 0 articles) while the chrome nav is already up. Issue #15 filed that as
# no-reply-button. Probe the focal article separately so we can reload
# once and name empty-shell vs a real missing reply control.
FOCAL_PROBE_JS = """((sid) => {
  const articles = [...document.querySelectorAll('article')];
  const focal = articles.find(a =>
    a.querySelector('a[href*="/status/' + sid + '"] time'));
  const reply = focal && focal.querySelector('[data-testid="reply"]');
  const r = reply && reply.getBoundingClientRect();
  return JSON.stringify({nArticles: articles.length, focal: !!focal,
                         reply: !!(r && r.width)});
})"""

CLICK_APPEAR_TIMEOUT = 8.0

EVIDENCE_JS = """((frag) => {
  const arts = [...document.querySelectorAll('[data-testid="tweet"]')];
  for (const a of arts.slice(0, 12)) {
    const link = a.querySelector('a[href*="/status/"]');
    const txt = a.querySelector('[data-testid="tweetText"]');
    if (link && txt && txt.innerText.includes(frag)) {
      const m = link.getAttribute('href')
        .match(/\\/[A-Za-z0-9_]{1,15}\\/status\\/\\d+/);
      if (m) return JSON.stringify({url: 'https://x.com' + m[0],
                                    text: txt.innerText.slice(0, 400)});
    }
  }
  return null;
})"""


def _dialog_gate_js(text: str) -> str:
    return """((text) => {
  const editor = [...document.querySelectorAll('div[role="dialog"]')]
    .flatMap(d => [...d.querySelectorAll('[data-testid^="tweetTextarea_"]')])
    .find(e => e.getAttribute('contenteditable') === 'true');
  const value = editor ? (editor.textContent || '') : '';
  if (!value.includes(text)) {
    return JSON.stringify({ok: false, stage: 'text-gate',
      detail: 'text not present in editor: ' + value.slice(0, 120)});
  }
  const btn = [...document.querySelectorAll('div[role="dialog"]')]
    .flatMap(d => [...d.querySelectorAll('[data-testid="tweetButton"]')])
    .find(b => b);
  if (!btn) return JSON.stringify({ok: false, stage: 'no-submit-btn',
    detail: 'no tweetButton in dialog'});
  if (btn.getAttribute('aria-disabled') === 'true')
    return JSON.stringify({ok: false, stage: 'btn-disabled',
      detail: 'submit disabled — X did not register the text'});
  return JSON.stringify({ok: true, stage: 'gates-passed',
    detail: value.slice(0, 200)});
})""" + f"({json.dumps(text)})"


def _wait_eval(cdp, js: str, timeout: float = CLICK_APPEAR_TIMEOUT,
               interval: float = 0.5):
    """Poll js until it returns a truthy value. At least one evaluate."""
    deadline = time.monotonic() + timeout
    last = None
    while True:
        last = cdp.evaluate(js)
        if last:
            return last
        if time.monotonic() >= deadline:
            return last
        time.sleep(interval)


def _poll_json(cdp, js: str, pred, timeout: float = CLICK_APPEAR_TIMEOUT,
               interval: float = 0.5) -> dict:
    """Poll a JSON probe until pred(state) or timeout. At least one evaluate."""
    deadline = time.monotonic() + timeout
    last: dict = {}
    while True:
        raw = cdp.evaluate(js)
        if raw:
            last = json.loads(raw)
            if pred(last):
                return last
        if time.monotonic() >= deadline:
            return last
        time.sleep(interval)


def _hydrate_permalink(cdp, url: str, status_id: str) -> dict:
    """Wait for the focal article; one reload if the permalink is empty."""
    probe = FOCAL_PROBE_JS + f"({json.dumps(status_id)})"
    state = _poll_json(cdp, probe, lambda s: s.get("focal"))
    if state.get("focal"):
        return state
    cdp.goto(url, settle=4.0)
    return _poll_json(cdp, probe, lambda s: s.get("focal"))


def _fail_if_permalink_unusable(cdp, url: str, status_id: str,
                                action: str) -> dict:
    state = _hydrate_permalink(cdp, url, status_id)
    if not state.get("focal"):
        _fail_gate(action, url,
                   {"stage": "empty-shell",
                    "detail": "permalink never rendered the focal article "
                              f"(articles={state.get('nArticles', 0)})"},
                   "", cdp)
    if action == "reply" and not state.get("reply"):
        _fail_gate(action, url,
                   {"stage": "no-reply-button",
                    "detail": "focal article rendered but reply control "
                              "missing or zero rect"},
                   "", cdp)
    return state


def _click_center(cdp, js: str, action: str, stage: str,
                  target_url: str | None, cdp_for_shot=None) -> None:
    """Trusted click at the center of the element js resolves to.

    js must scroll the element into view (behavior:'instant' — X uses CSS
    smooth scrolling, so a plain scrollIntoView animates and the rect read
    races the scroll: the 09-03 14:xx click failures all landed at stale
    coordinates). Wait for the locator to appear (permalinks hydrate after
    readyState complete — issue #15) then require a stable rect across two
    polls before the mouse events dispatch.
    """
    raw = _wait_eval(cdp, js)
    if not raw:
        _fail_gate(action, target_url,
                   {"stage": stage,
                    "detail": "element not found or zero rect"},
                   "", cdp_for_shot)
    prev = json.loads(raw)
    pos = prev
    for _ in range(5):
        time.sleep(0.35)
        raw = cdp.evaluate(js)
        if not raw:
            _fail_gate(action, target_url,
                       {"stage": stage,
                        "detail": "element not found or zero rect"},
                       "", cdp_for_shot)
        pos = json.loads(raw)
        if abs(prev["x"] - pos["x"]) < 1 and abs(prev["y"] - pos["y"]) < 1:
            break
        prev = pos
    for tp, kwargs in (("mousePressed", {"button": "left", "clickCount": 1}),
                       ("mouseReleased", {"button": "left", "clickCount": 1})):
        cdp.command("Input.dispatchMouseEvent",
                    {"type": tp, "x": pos["x"], "y": pos["y"], **kwargs},
                    timeout=15)


def _fail_gate(action: str, target_url: str | None, gates: dict,
               text: str, cdp=None) -> None:
    sig = f"{action}:{gates.get('stage', 'gate-failed')}"
    shot = failure.save_screenshot(cdp, signature=sig)
    fields = failure.report_bug(
        action, sig, gates.get("stage", "gate-failed"),
        f"recipe gate failed at stage '{gates.get('stage')}': "
        f"{gates.get('detail', '')}",
        diagnostics={"url": target_url, "text_len": len(text)},
        screenshot=shot)
    envelope.fail(action, envelope.BUG, gates.get("stage"),
                  f"gate '{gates.get('stage')}' failed: "
                  f"{gates.get('detail', '')}",
                  diagnostics={"url": target_url}, signature=sig,
                  screenshot=shot, **fields)


def _await_modal(cdp, action: str, target_url: str | None, text: str,
                 checks: list[str]) -> None:
    """Poll dialog gates up to ~3s; all must pass, else gated failure."""
    state: dict = {}
    for _ in range(3):
        time.sleep(1.0)
        state = {}
        for js in checks:
            state = json.loads(cdp.evaluate(js) or '{"ok":false}')
            if not state.get("ok"):
                break
        if state.get("ok"):
            return
    _fail_gate(action, target_url, state, text, cdp)


ATTACHMENTS_JS = """(() => {
  const d = [...document.querySelectorAll('div[role="dialog"]')]
    .find(d => d.querySelector('[data-testid^="tweetTextarea_"]'));
  if (!d) return JSON.stringify({n: -1});
  const box = d.querySelector('[data-testid="attachments"]');
  const imgs = box ? [...box.querySelectorAll('img')].filter(i => (i.src || '').startsWith('blob:')) : [];
  return JSON.stringify({n: imgs.length});
})()"""


def _focal_js(sid: str, selector: str) -> str:
    """Rect of `selector` inside the focal article (instant scroll)."""
    return """(() => {
  const focal = [...document.querySelectorAll('article')]
    .find(a => a.querySelector('a[href*="/status/%s"] time'));
  if (!focal) return null;
  const btn = focal.querySelector('%s');
  if (!btn) return null;
  btn.scrollIntoView({block: 'center', behavior: 'instant'});
  const r = btn.getBoundingClientRect();
  if (!r || !r.width) return null;
  return JSON.stringify({x: r.x + r.width / 2, y: r.y + r.height / 2});
})()""" % (sid, selector)


def _focal_state_js(sid: str, on: str, off: str) -> str:
    return """(() => {
  const focal = [...document.querySelectorAll('article')]
    .find(a => a.querySelector('a[href*="/status/%s"] time'));
  if (!focal) return JSON.stringify({focal: false});
  return JSON.stringify({focal: true,
    on: !!focal.querySelector('[data-testid="%s"]'),
    off: !!focal.querySelector('[data-testid="%s"]')});
})()""" % (sid, on, off)


MENU_ITEMS_JS = """(() => JSON.stringify([...document.querySelectorAll('[role="menuitem"]')]
  .map(e => ({tid: e.getAttribute('data-testid'), text: (e.innerText || '').trim().slice(0, 60)}))))()"""


def _menu_item_js(kind: str) -> str:
    test = ("e.getAttribute('data-testid') === 'retweetConfirm'" if kind == "repost"
            else "/^(cita|quote)/i.test((e.innerText || '').trim())")
    return """(() => {
  const it = [...document.querySelectorAll('[role="menuitem"]')].find(e => %s);
  if (!it) return null;
  it.scrollIntoView({block: 'center', behavior: 'instant'});
  const r = it.getBoundingClientRect();
  if (!r || !r.width) return null;
  return JSON.stringify({x: r.x + r.width / 2, y: r.y + r.height / 2});
})()""" % test


def _follow_js(handle: str, suffix: str) -> str:
    return """(() => {
  const h = '@%s'.toLowerCase();
  const btn = [...document.querySelectorAll('[data-testid$="%s"]')]
    .find(b => (b.getAttribute('aria-label') || '').toLowerCase().includes(h));
  if (!btn) return null;
  btn.scrollIntoView({block: 'center', behavior: 'instant'});
  const r = btn.getBoundingClientRect();
  if (!r || !r.width) return null;
  return JSON.stringify({x: r.x + r.width / 2, y: r.y + r.height / 2});
})()""" % (handle, suffix)


def _follow_state_js(handle: str) -> str:
    return """(() => {
  const h = '@%s'.toLowerCase();
  const find = suf => [...document.querySelectorAll('[data-testid$="' + suf + '"]')]
    .some(b => (b.getAttribute('aria-label') || '').toLowerCase().includes(h));
  return JSON.stringify({follow: find('-follow'), unfollow: find('-unfollow')});
})()""" % handle


def _press_escape(cdp) -> None:
    for tp in ("keyDown", "keyUp"):
        cdp.command("Input.dispatchKeyEvent",
                    {"type": tp, "key": "Escape", "code": "Escape",
                     "windowsVirtualKeyCode": 27}, timeout=15)


def _require_cap(action: str, kind: str, target: str | None) -> str:
    ok, detail = caps.check(kind)
    if not ok:
        envelope.fail(action, envelope.BUG, "cap-reached",
                      f"daily cap reached: {detail}",
                      diagnostics={"url": target, "kind": kind})
    return detail


def validate_media(paths: list[str] | None) -> list[str]:
    """Only images rendered by tools/render.py may be attached: inside
    renders/, a supported type, <= 5 MB, and a `<file>.json` sidecar whose
    sha256 matches the bytes. Raises ValueError with the reason."""
    out = []
    for raw in paths or []:
        pth = Path(raw).expanduser().resolve()
        try:
            pth.relative_to(RENDERS.resolve())
        except ValueError:
            raise ValueError(f"{raw}: media must live under renders/ (rendered from a template, never a screenshot)")
        if pth.suffix.lower() not in MEDIA_EXT:
            raise ValueError(f"{raw}: unsupported type {pth.suffix}")
        if not pth.is_file():
            raise ValueError(f"{raw}: not a file")
        if pth.stat().st_size > MEDIA_MAX_BYTES:
            raise ValueError(f"{raw}: larger than {MEDIA_MAX_BYTES // 1024 // 1024} MB")
        side = Path(str(pth) + ".json")
        if not side.is_file():
            raise ValueError(f"{raw}: no render sidecar {side.name}")
        try:
            meta = json.loads(side.read_text())
        except json.JSONDecodeError:
            raise ValueError(f"{raw}: sidecar is not JSON")
        digest = hashlib.sha256(pth.read_bytes()).hexdigest()
        if meta.get("sha256") != digest or meta.get("renderer") != "tools/render.py":
            raise ValueError(f"{raw}: sidecar does not match the file (not produced by render.py)")
        out.append(str(pth))
    if len(out) > MEDIA_MAX_COUNT:
        raise ValueError(f"at most {MEDIA_MAX_COUNT} images per post")
    return out


def _attach_media(cdp, paths: list[str], action: str, target_url: str | None) -> None:
    """Hand the files to the composer's hidden <input type=file> through
    CDP (no clicks, no OS dialog) and wait for the blob previews."""
    if not paths:
        return
    doc = cdp.command("DOM.getDocument", {"depth": -1, "pierce": True}, timeout=15)
    node = cdp.command("DOM.querySelector",
                       {"nodeId": doc["root"]["nodeId"],
                        "selector": 'div[role="dialog"] input[data-testid="fileInput"]'},
                       timeout=15)
    if not node.get("nodeId"):
        _fail_gate(action, target_url, {"stage": "no-file-input",
                                        "detail": "composer has no fileInput"}, "", cdp)
    cdp.command("DOM.setFileInputFiles", {"nodeId": node["nodeId"], "files": paths}, timeout=15)
    deadline = time.monotonic() + 20.0
    n = -1
    while time.monotonic() < deadline:
        time.sleep(0.8)
        n = json.loads(cdp.evaluate(ATTACHMENTS_JS) or '{"n":-1}').get("n", -1)
        if n >= len(paths):
            return
    _fail_gate(action, target_url, {"stage": "media-not-attached",
                                    "detail": f"{n} of {len(paths)} previews rendered"}, "", cdp)


def _register_item(evidence: dict, tag: dict | None) -> bool:
    """memory/items.json row for what was just published (items.py). A
    failure here is logged, never raised: the post is already out."""
    if not tag or not evidence.get("url"):
        return False
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        import items as items_mod  # noqa: WPS433
        from datetime import datetime
        followers = None
        try:
            stats = json.loads((ROOT / "memory" / "stats.json").read_text())
            followers = (stats.get("daily") or [{}])[0].get("followers")
        except (OSError, json.JSONDecodeError, IndexError):
            pass
        d = items_mod.load(items_mod.DEFAULT_FILE)
        now = datetime.now().astimezone()
        items_mod.add(d, evidence["url"], now=now, kind=tag.get("kind", "reply"),
                      series=tag.get("series"), model=tag.get("model") or os.environ.get("X_AGENT_MODEL"),
                      parent=tag.get("parent"), text=evidence.get("text"), followers=followers)
        items_mod.save(items_mod.DEFAULT_FILE, d, now)
        return True
    except Exception as e:  # noqa: BLE001
        envelope.log(f"items.json registration failed: {type(e).__name__}: {e}")
        return False


def _submit_and_verify(cdp, action: str, target_url: str | None,
                       text: str, check_only: bool, *, expect_media: int = 0,
                       cap_kind: str | None = None, tag: dict | None = None) -> None:
    gates = json.loads(cdp.evaluate(_dialog_gate_js(text))
                       or '{"ok":false,"stage":"gate-null"}')
    if not gates.get("ok"):
        _fail_gate(action, target_url, gates, text, cdp)
    if expect_media:
        n = json.loads(cdp.evaluate(ATTACHMENTS_JS) or '{"n":-1}').get("n", -1)
        if n < expect_media:
            _fail_gate(action, target_url, {"stage": "media-not-attached",
                                            "detail": f"{n} of {expect_media} previews"}, text, cdp)

    if check_only:
        envelope.emit(action, {"checked": True, "text": text, "media": expect_media,
                               "stage": "gates-passed-not-submitted"})
        return

    _click_center(cdp, DIALOG_SUBMIT_JS, action, "submit-btn-gone",
                  target_url, cdp)
    time.sleep(1.0)

    probe = EVIDENCE_JS + f"({json.dumps(text[:80])})"
    evidence = None
    deadline = time.monotonic() + SUBMIT_TIMEOUT
    while time.monotonic() < deadline and evidence is None:
        time.sleep(2.5)
        raw = cdp.evaluate(probe)
        if raw:
            evidence = json.loads(raw)
            break
        cdp.goto(f"https://x.com/{session.OWNER_HANDLE}"
                 + ("/with_replies" if action == "reply" else ""),
                 settle=2.5)
    if evidence is None:
        sig = f"{action}:no-evidence"
        shot = failure.save_screenshot(cdp, sig)
        fields = failure.report_bug(
            action, sig, "no-evidence",
            "submit clicked but published item never appeared within "
            "timeout",
            diagnostics={"url": target_url, "text": text[:120]},
            screenshot=shot)
        envelope.fail(action, envelope.BUG, "no-evidence",
                      "submitted but no verified evidence of publication",
                      diagnostics={"url": target_url}, signature=sig,
                      screenshot=shot, **fields)
    if cap_kind:
        evidence["caps"] = caps.consume(cap_kind)
    evidence["item_registered"] = _register_item(evidence, tag)
    envelope.emit(action, evidence)


def reply(url: str, text: str, check_only: bool = False,
          media: list[str] | None = None, model: str | None = None) -> None:
    m = re.match(r"https?://(?:www\.)?x\.com/([A-Za-z0-9_]{1,15})/status/"
                 r"(\d+)", url or "")
    if not m:
        envelope.fail("reply", envelope.BUG, "bad-url",
                      f"cannot parse handle/status id from: {url}",
                      diagnostics={"url": url})
    handle, status_id = m.group(1), m.group(2)
    try:
        media = validate_media(media)
    except ValueError as e:
        envelope.fail("reply", envelope.BUG, "media-policy", str(e), diagnostics={"url": url})
    _require_cap("reply", "reply", url)
    cdp = session.open_tab(url, "reply")
    try:
        session.assert_owner_session(cdp, "reply")
        cdp.goto(url, settle=4.0)
        # Permalinks can be an empty shell after settle (issue #15). Hydrate
        # / reload before treating a missing reply button as a restriction.
        _fail_if_permalink_unusable(cdp, url, status_id, "reply")
        # focus seed: the FOCAL post's reply button (08-31 Path B).
        # A trusted click on a button reliably lands; the modal composer
        # then AUTO-FOCUSES — no clicks into composers anywhere in the path.
        _click_center(cdp, REPLY_BUTTON_JS + f"({json.dumps(status_id)})",
                      "reply", "no-reply-button", url, cdp)
        # verify the modal targets the right parent and is auto-focused
        _await_modal(cdp, "reply", url, text,
                     [TARGET_JS + f"({json.dumps(handle)})",
                      DIALOG_FOCUS_JS])
        cdp.command("Input.insertText", {"text": text}, timeout=15)
        time.sleep(0.8)
        _attach_media(cdp, media, "reply", url)
        _submit_and_verify(cdp, "reply", url, text, check_only, expect_media=len(media),
                           cap_kind="reply", tag={"kind": "reply", "parent": url, "model": model})
    finally:
        cdp.close()


def post(text: str, check_only: bool = False, media: list[str] | None = None,
         series: str | None = None, model: str | None = None) -> None:
    try:
        media = validate_media(media)
    except ValueError as e:
        envelope.fail("post", envelope.BUG, "media-policy", str(e))
    _require_cap("post", "original", None)
    cdp = session.open_tab("https://x.com/compose/post", "post")
    try:
        session.assert_owner_session(cdp, "post")
        cdp.goto("https://x.com/compose/post", settle=4.0)
        _await_modal(cdp, "post", None, text, [DIALOG_FOCUS_JS])
        cdp.command("Input.insertText", {"text": text}, timeout=15)
        time.sleep(0.8)
        _attach_media(cdp, media, "post", None)
        _submit_and_verify(cdp, "post", None, text, check_only, expect_media=len(media),
                           cap_kind="original", tag={"kind": "original", "series": series, "model": model})
    finally:
        cdp.close()


def _parse_status(url: str, action: str) -> tuple[str, str]:
    m = re.match(r"https?://(?:www\.)?x\.com/([A-Za-z0-9_]{1,15})/status/(\d+)", url or "")
    if not m:
        envelope.fail(action, envelope.BUG, "bad-url",
                      f"cannot parse handle/status id from: {url}", diagnostics={"url": url})
    return m.group(1), m.group(2)


def _toggle_state(cdp, sid: str, on: str, off: str) -> dict:
    return json.loads(cdp.evaluate(_focal_state_js(sid, on, off)) or '{"focal":false}')


def like(url: str, check_only: bool = False) -> None:
    handle, sid = _parse_status(url, "like")
    cdp = session.open_tab(url, "like")
    try:
        session.assert_owner_session(cdp, "like")
        cdp.goto(url, settle=4.0)
        _fail_if_permalink_unusable(cdp, url, sid, "like")
        st = _toggle_state(cdp, sid, "unlike", "like")
        if st.get("on"):
            envelope.emit("like", {"url": url, "already_liked": True})
        if not st.get("off"):
            _fail_gate("like", url, {"stage": "no-like-button", "detail": "focal article has no like control"}, "", cdp)
        detail = _require_cap("like", "like", url)
        if check_only:
            envelope.emit("like", {"checked": True, "url": url, "caps": detail,
                                   "stage": "gates-passed-not-submitted"})
        _click_center(cdp, _focal_js(sid, '[data-testid="like"]'), "like", "like-btn-gone", url, cdp)
        st = _poll_json(cdp, _focal_state_js(sid, "unlike", "like"), lambda s: s.get("on"))
        if not st.get("on"):
            _fail_gate("like", url, {"stage": "like-not-confirmed", "detail": "unlike control never appeared"}, "", cdp)
        envelope.emit("like", {"url": url, "liked": True, "caps": caps.consume("like")})
    finally:
        cdp.close()


def _open_retweet_menu(cdp, sid: str, action: str, url: str) -> list[dict]:
    _click_center(cdp, _focal_js(sid, '[data-testid="retweet"], [data-testid="unretweet"]'),
                  action, "no-retweet-button", url, cdp)
    items: list[dict] = []
    deadline = time.monotonic() + CLICK_APPEAR_TIMEOUT
    while time.monotonic() < deadline and not items:
        time.sleep(0.6)
        items = json.loads(cdp.evaluate(MENU_ITEMS_JS) or "[]")
    if not items:
        _fail_gate(action, url, {"stage": "no-retweet-menu", "detail": "menu never rendered"}, "", cdp)
    return items


def repost(url: str, check_only: bool = False) -> None:
    handle, sid = _parse_status(url, "repost")
    cdp = session.open_tab(url, "repost")
    try:
        session.assert_owner_session(cdp, "repost")
        cdp.goto(url, settle=4.0)
        _fail_if_permalink_unusable(cdp, url, sid, "repost")
        st = _toggle_state(cdp, sid, "unretweet", "retweet")
        if st.get("on"):
            envelope.emit("repost", {"url": url, "already_reposted": True})
        detail = _require_cap("repost", "repost", url)
        items = _open_retweet_menu(cdp, sid, "repost", url)
        if not any(i.get("tid") == "retweetConfirm" for i in items):
            _press_escape(cdp)
            _fail_gate("repost", url, {"stage": "no-repost-item",
                                       "detail": "menu items: " + ", ".join(i.get("text", "") for i in items)}, "", cdp)
        if check_only:
            _press_escape(cdp)
            envelope.emit("repost", {"checked": True, "url": url, "caps": detail,
                                     "menu": [i.get("text") for i in items],
                                     "stage": "gates-passed-not-submitted"})
        _click_center(cdp, _menu_item_js("repost"), "repost", "repost-item-gone", url, cdp)
        st = _poll_json(cdp, _focal_state_js(sid, "unretweet", "retweet"), lambda s: s.get("on"))
        if not st.get("on"):
            _fail_gate("repost", url, {"stage": "repost-not-confirmed", "detail": "unretweet control never appeared"}, "", cdp)
        envelope.emit("repost", {"url": url, "reposted": True, "caps": caps.consume("repost")})
    finally:
        cdp.close()


def quote(url: str, text: str, check_only: bool = False, media: list[str] | None = None,
          series: str | None = None, model: str | None = None) -> None:
    handle, sid = _parse_status(url, "quote")
    try:
        media = validate_media(media)
    except ValueError as e:
        envelope.fail("quote", envelope.BUG, "media-policy", str(e), diagnostics={"url": url})
    _require_cap("quote", "original", url)
    cdp = session.open_tab(url, "quote")
    try:
        session.assert_owner_session(cdp, "quote")
        cdp.goto(url, settle=4.0)
        _fail_if_permalink_unusable(cdp, url, sid, "quote")
        items = _open_retweet_menu(cdp, sid, "quote", url)
        if not any(re.match(r"^(cita|quote)", i.get("text", ""), re.I) for i in items):
            _press_escape(cdp)
            _fail_gate("quote", url, {"stage": "no-quote-item",
                                      "detail": "menu items: " + ", ".join(i.get("text", "") for i in items)}, "", cdp)
        _click_center(cdp, _menu_item_js("quote"), "quote", "quote-item-gone", url, cdp)
        # the modal composer embeds the quoted post: same target + focus gates as a reply
        _await_modal(cdp, "quote", url, text, [TARGET_JS + f"({json.dumps(handle)})", DIALOG_FOCUS_JS])
        cdp.command("Input.insertText", {"text": text}, timeout=15)
        time.sleep(0.8)
        _attach_media(cdp, media, "quote", url)
        _submit_and_verify(cdp, "quote", url, text, check_only, expect_media=len(media),
                           cap_kind="original", tag={"kind": "quote", "parent": url, "series": series, "model": model})
    finally:
        cdp.close()


def follow(handle: str, reason: str, check_only: bool = False) -> None:
    handle = handle.lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle):
        envelope.fail("follow", envelope.BUG, "bad-handle", f"not a handle: {handle}")
    if not (reason or "").strip():
        envelope.fail("follow", envelope.BUG, "reason-required",
                      "the Floor allows a follow only for a stated reason (follow-back, a reply to us)")
    url = f"https://x.com/{handle}"
    cdp = session.open_tab(url, "follow")
    try:
        session.assert_owner_session(cdp, "follow")
        cdp.goto(url, settle=4.0)
        st = _poll_json(cdp, _follow_state_js(handle), lambda s: s.get("follow") or s.get("unfollow"))
        if st.get("unfollow"):
            envelope.emit("follow", {"handle": handle, "already_following": True})
        if not st.get("follow"):
            _fail_gate("follow", url, {"stage": "no-follow-button", "detail": f"no follow control for @{handle}"}, "", cdp)
        detail = _require_cap("follow", "follow", url)
        if check_only:
            envelope.emit("follow", {"checked": True, "handle": handle, "caps": detail,
                                     "reason": reason, "stage": "gates-passed-not-submitted"})
        _click_center(cdp, _follow_js(handle, "-follow"), "follow", "follow-btn-gone", url, cdp)
        st = _poll_json(cdp, _follow_state_js(handle), lambda s: s.get("unfollow"))
        if not st.get("unfollow"):
            _fail_gate("follow", url, {"stage": "follow-not-confirmed", "detail": "unfollow control never appeared"}, "", cdp)
        envelope.emit("follow", {"handle": handle, "followed": True, "reason": reason,
                                 "caps": caps.consume("follow")})
    finally:
        cdp.close()


BIO_FORM_JS = """(() => {
  const ta = document.querySelector('textarea[name="description"]');
  const btn = document.querySelector('[data-testid="Profile_Save_Button"]');
  if (!ta || !btn) return JSON.stringify({ok: false, stage: 'no-form',
    detail: 'ta=' + !!ta + ' btn=' + !!btn + ' url=' + location.href});
  return JSON.stringify({ok: true, stage: 'form-ready',
    current: (ta.value || '').slice(0, 160)});
})()"""

BIO_FILL_JS = """((text) => {
  const ta = document.querySelector('textarea[name="description"]');
  if (!ta) return JSON.stringify({ok: false, stage: 'no-bio-textarea'});
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(ta, text);
  ta.dispatchEvent(new Event('input', {bubbles: true}));
  ta.dispatchEvent(new Event('change', {bubbles: true}));
  return JSON.stringify({ok: ta.value === text, stage: 'filled',
    value: (ta.value || '').slice(0, 160)});
})"""

BIO_SAVE_JS = """(() => {
  const btn = document.querySelector('[data-testid="Profile_Save_Button"]');
  if (!btn) return null;
  if (btn.getAttribute('aria-disabled') === 'true' || btn.disabled) return null;
  btn.scrollIntoView({block: 'center', behavior: 'instant'});
  const r = btn.getBoundingClientRect();
  if (!r || !r.width) return null;
  return JSON.stringify({x: r.x + r.width / 2, y: r.y + r.height / 2});
})()"""

CARET_JS = """((sid) => {
  const focal = [...document.querySelectorAll('article')]
    .find(a => a.querySelector('a[href*="/status/' + sid + '"] time'));
  if (!focal) return null;
  const btn = focal.querySelector('[data-testid="caret"]');
  if (!btn) return null;
  btn.scrollIntoView({block: 'center', behavior: 'instant'});
  const r = btn.getBoundingClientRect();
  if (!r || !r.width) return null;
  return JSON.stringify({x: r.x + r.width / 2, y: r.y + r.height / 2});
})"""

PIN_MENU_PROBE_JS = """(() => {
  const items = [...document.querySelectorAll('[role="menuitem"]')];
  const labels = items.map(e => (e.innerText || '').trim().slice(0, 60));
  const pin = items.find(e => /fissa s[uo]l profilo|pin to your profile/i.test(e.innerText || ''));
  const unpin = items.find(e => /non fissare|togli dal profilo|unpin from/i.test(e.innerText || ''));
  return JSON.stringify({ok: !!(pin || unpin), already: !!unpin,
    n: items.length, labels});
})()"""

PIN_MENU_CLICK_JS = """(() => {
  const items = [...document.querySelectorAll('[role="menuitem"]')];
  const pin = items.find(e => /fissa s[uo]l profilo|pin to your profile/i.test(e.innerText || ''));
  if (!pin) return null;
  pin.scrollIntoView({block: 'center', behavior: 'instant'});
  const r = pin.getBoundingClientRect();
  if (!r || !r.width) return null;
  return JSON.stringify({x: r.x + r.width / 2, y: r.y + r.height / 2});
})()"""

PIN_CONFIRM_JS = """(() => {
  const btn = document.querySelector('[data-testid="confirmationSheetConfirm"]')
    || [...document.querySelectorAll('div[role="dialog"] [role="button"], div[role="dialog"] button')]
         .find(b => /fissa|pin/i.test(b.innerText || ''));
  if (!btn) return null;
  btn.scrollIntoView({block: 'center', behavior: 'instant'});
  const r = btn.getBoundingClientRect();
  if (!r || !r.width) return null;
  return JSON.stringify({x: r.x + r.width / 2, y: r.y + r.height / 2});
})()"""

DELETE_MENU_PROBE_JS = """(() => {
  const items = [...document.querySelectorAll('[role="menuitem"]')];
  const labels = items.map(e => (e.innerText || '').trim().slice(0, 60));
  const del = items.find(e => /^(elimina|delete)\\b/i.test((e.innerText || '').trim()));
  return JSON.stringify({ok: !!del, n: items.length, labels});
})()"""

DELETE_MENU_CLICK_JS = """(() => {
  const items = [...document.querySelectorAll('[role="menuitem"]')];
  const del = items.find(e => /^(elimina|delete)\\b/i.test((e.innerText || '').trim()));
  if (!del) return null;
  del.scrollIntoView({block: 'center', behavior: 'instant'});
  const r = del.getBoundingClientRect();
  if (!r || !r.width) return null;
  return JSON.stringify({x: r.x + r.width / 2, y: r.y + r.height / 2});
})()"""

DELETE_CONFIRM_JS = """(() => {
  const btn = document.querySelector('[data-testid="confirmationSheetConfirm"]')
    || [...document.querySelectorAll('div[role="dialog"] [role="button"], div[role="dialog"] button')]
         .find(b => /^(elimina|delete)$/i.test((b.innerText || '').trim()));
  if (!btn) return null;
  btn.scrollIntoView({block: 'center', behavior: 'instant'});
  const r = btn.getBoundingClientRect();
  if (!r || !r.width) return null;
  return JSON.stringify({x: r.x + r.width / 2, y: r.y + r.height / 2});
})()"""

# After the confirm, our profile must render posts and none of them may be
# the recalled one: the permalink alone cannot tell "gone" from "empty shell".
DELETE_GONE_JS = """((sid) => {
  const arts = [...document.querySelectorAll('article')];
  const present = arts.some(a => a.querySelector('a[href*="/status/' + sid + '"]'));
  return JSON.stringify({articles: arts.length, present});
})"""


def bio(text: str, check_only: bool = False) -> None:
    text = (text or "").strip()
    if not text or len(text) > 160:
        envelope.fail("bio", envelope.BUG, "bad-bio",
                      f"bio must be 1-160 chars, got {len(text)}")
    cdp = session.open_tab("https://x.com/settings/profile", "bio")
    try:
        session.assert_owner_session(cdp, "bio")
        cdp.goto("https://x.com/settings/profile", settle=4.0)
        state = {}
        for _ in range(6):
            time.sleep(0.8)
            state = json.loads(cdp.evaluate(BIO_FORM_JS) or '{"ok":false}')
            if state.get("ok"):
                break
        if not state.get("ok"):
            _fail_gate("bio", None, state or {"stage": "no-form"}, text, cdp)
        if check_only:
            envelope.emit("bio", {"checked": True, "text": text,
                                  "stage": "form-ready-not-submitted",
                                  "current": state.get("current")})
            return
        filled = json.loads(
            cdp.evaluate(BIO_FILL_JS + f"({json.dumps(text)})")
            or '{"ok":false}')
        if not filled.get("ok"):
            _fail_gate("bio", None, {"stage": "text-gate",
                                     "detail": filled.get("value", "")},
                       text, cdp)
        enabled = False
        for _ in range(10):
            if cdp.evaluate(BIO_SAVE_JS):
                enabled = True
                break
            time.sleep(0.4)
        if not enabled:
            _fail_gate("bio", None,
                       {"stage": "save-disabled",
                        "detail": "Save stayed disabled after fill"},
                       text, cdp)
        _click_center(cdp, BIO_SAVE_JS, "bio", "save-btn-gone", None, cdp)
        evidence = None
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline and evidence is None:
            time.sleep(2.0)
            cdp.goto(f"https://x.com/{session.OWNER_HANDLE}", settle=2.5)
            raw = cdp.evaluate("""(() => {
              const bio = document.querySelector('[data-testid="UserDescription"]');
              return bio ? bio.innerText : null;
            })()""")
            if raw and text[:40] in raw:
                evidence = {"bio": raw,
                            "url": f"https://x.com/{session.OWNER_HANDLE}"}
                break
        if evidence is None:
            sig = "bio:no-evidence"
            shot = failure.save_screenshot(cdp, sig)
            fields = failure.report_bug(
                "bio", sig, "no-evidence",
                "save clicked but profile bio never matched",
                diagnostics={"text": text[:120]}, screenshot=shot)
            envelope.fail("bio", envelope.BUG, "no-evidence",
                          "submitted but profile bio did not match",
                          signature=sig, screenshot=shot, **fields)
        envelope.emit("bio", evidence)
    finally:
        cdp.close()


def pin(url: str, check_only: bool = False) -> None:
    m = re.match(r"https?://(?:www\.)?x\.com/([A-Za-z0-9_]{1,15})/status/"
                 r"(\d+)", url or "")
    if not m:
        envelope.fail("pin", envelope.BUG, "bad-url",
                      f"cannot parse handle/status id from: {url}",
                      diagnostics={"url": url})
    handle, status_id = m.group(1), m.group(2)
    if handle.lower() != session.OWNER_HANDLE.lower():
        envelope.fail("pin", envelope.BUG, "not-ours",
                      f"can only pin our own posts, got @{handle}",
                      diagnostics={"url": url})
    cdp = session.open_tab(url, "pin")
    try:
        session.assert_owner_session(cdp, "pin")
        cdp.goto(url, settle=4.0)
        _fail_if_permalink_unusable(cdp, url, status_id, "pin")
        _click_center(cdp, CARET_JS + f"({json.dumps(status_id)})",
                      "pin", "no-caret", url, cdp)
        probe = {}
        for _ in range(5):
            time.sleep(0.6)
            probe = json.loads(cdp.evaluate(PIN_MENU_PROBE_JS)
                               or '{"ok":false}')
            if probe.get("ok"):
                break
        if not probe.get("ok"):
            _fail_gate("pin", url, {"stage": "no-pin-item",
                                    "detail": json.dumps(probe)}, "", cdp)
        if probe.get("already"):
            envelope.emit("pin", {"url": url, "already_pinned": True})
            return
        if check_only:
            envelope.emit("pin", {"checked": True, "url": url,
                                  "stage": "pin-item-visible-not-submitted",
                                  "labels": probe.get("labels")})
            return
        _click_center(cdp, PIN_MENU_CLICK_JS, "pin", "pin-item-gone",
                      url, cdp)
        confirm = None
        for _ in range(6):
            time.sleep(0.5)
            confirm = cdp.evaluate(PIN_CONFIRM_JS)
            if confirm:
                break
        if not confirm:
            _fail_gate("pin", url, {"stage": "no-confirm",
                                    "detail": "pin confirm sheet missing"},
                       "", cdp)
        _click_center(cdp, PIN_CONFIRM_JS, "pin", "confirm-gone", url, cdp)
        evidence = None
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline and evidence is None:
            time.sleep(2.0)
            cdp.goto(f"https://x.com/{session.OWNER_HANDLE}", settle=2.5)
            raw = cdp.evaluate("""((sid) => {
              const ctx = [...document.querySelectorAll(
                '[data-testid="socialContext"], [data-testid="icon-pin"]')];
              const pinned = ctx.some(e =>
                /fissat|pinned/i.test(e.innerText || e.getAttribute('aria-label') || '')
                || (e.getAttribute('data-testid') || '') === 'icon-pin');
              const first = document.querySelector(
                '[data-testid="tweet"] a[href*="/status/"]');
              const href = first ? first.getAttribute('href') : '';
              return JSON.stringify({pinned, href, sidMatch: href.includes(sid)});
            })""" + f"({json.dumps(status_id)})")
            if raw:
                d = json.loads(raw)
                if d.get("pinned") or d.get("sidMatch"):
                    evidence = {"url": url, **d}
                    break
        if evidence is None:
            sig = "pin:no-evidence"
            shot = failure.save_screenshot(cdp, sig)
            fields = failure.report_bug(
                "pin", sig, "no-evidence",
                "confirm clicked but pin not visible on profile",
                diagnostics={"url": url}, screenshot=shot)
            envelope.fail("pin", envelope.BUG, "no-evidence",
                          "submitted but pin not visible on profile",
                          diagnostics={"url": url}, signature=sig,
                          screenshot=shot, **fields)
        envelope.emit("pin", evidence)
    finally:
        cdp.close()


def _close_item(url: str) -> bool:
    """Close the items.json row of a recalled post so `items.py collect`
    stops measuring it. Logged, never raised: the recall already happened."""
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        import items as items_mod  # noqa: WPS433
        from datetime import datetime
        d = items_mod.load(items_mod.DEFAULT_FILE)
        it = items_mod.find(d, url)
        if it is None:
            return False
        now = datetime.now().astimezone()
        it["closed"], it["recalled"] = True, now.isoformat(timespec="minutes")
        items_mod.save(items_mod.DEFAULT_FILE, d, now)
        return True
    except Exception as e:  # noqa: BLE001
        envelope.log(f"items.json close failed: {type(e).__name__}: {e}")
        return False


def delete(url: str, check_only: bool = False) -> None:
    """Recall one of OUR posts: caret menu → Elimina/Delete → confirmation
    sheet → verified gone from the profile. No cap (it undoes, never adds);
    the items.json row is closed so the scheduler stops measuring it."""
    handle, status_id = _parse_status(url, "delete")
    if handle.lower() != session.OWNER_HANDLE.lower():
        envelope.fail("delete", envelope.BUG, "not-ours",
                      f"can only recall our own posts, got @{handle}",
                      diagnostics={"url": url})
    cdp = session.open_tab(url, "delete")
    try:
        session.assert_owner_session(cdp, "delete")
        cdp.goto(url, settle=4.0)
        _fail_if_permalink_unusable(cdp, url, status_id, "delete")
        _click_center(cdp, CARET_JS + f"({json.dumps(status_id)})",
                      "delete", "no-caret", url, cdp)
        probe = {}
        for _ in range(5):
            time.sleep(0.6)
            probe = json.loads(cdp.evaluate(DELETE_MENU_PROBE_JS) or '{"ok":false}')
            if probe.get("ok"):
                break
        if not probe.get("ok"):
            _press_escape(cdp)
            _fail_gate("delete", url, {"stage": "no-delete-item",
                                       "detail": json.dumps(probe)}, "", cdp)
        if check_only:
            _press_escape(cdp)
            envelope.emit("delete", {"checked": True, "url": url,
                                     "stage": "delete-item-visible-not-submitted",
                                     "labels": probe.get("labels")})
        _click_center(cdp, DELETE_MENU_CLICK_JS, "delete", "delete-item-gone", url, cdp)
        confirm = None
        for _ in range(6):
            time.sleep(0.5)
            confirm = cdp.evaluate(DELETE_CONFIRM_JS)
            if confirm:
                break
        if not confirm:
            _press_escape(cdp)
            _fail_gate("delete", url, {"stage": "no-confirm",
                                       "detail": "confirmation sheet missing"}, "", cdp)
        _click_center(cdp, DELETE_CONFIRM_JS, "delete", "confirm-gone", url, cdp)
        evidence = None
        deadline = time.monotonic() + 25.0
        while time.monotonic() < deadline and evidence is None:
            time.sleep(2.0)
            cdp.goto(f"https://x.com/{session.OWNER_HANDLE}/with_replies", settle=2.5)
            raw = cdp.evaluate(DELETE_GONE_JS + f"({json.dumps(status_id)})")
            if raw:
                d = json.loads(raw)
                if d.get("articles", 0) > 0 and not d.get("present"):
                    evidence = {"url": url, "recalled": True, **d}
        if evidence is None:
            sig = "delete:no-evidence"
            shot = failure.save_screenshot(cdp, sig)
            fields = failure.report_bug(
                "delete", sig, "no-evidence",
                "confirm clicked but the post still shows on the profile "
                "(or the profile did not render)",
                diagnostics={"url": url}, screenshot=shot)
            envelope.fail("delete", envelope.BUG, "no-evidence",
                          "submitted but the post is still visible on the profile",
                          diagnostics={"url": url}, signature=sig,
                          screenshot=shot, **fields)
        evidence["item_closed"] = _close_item(url)
        envelope.emit("delete", evidence)
    finally:
        cdp.close()
