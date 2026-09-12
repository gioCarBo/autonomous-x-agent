"""x — deterministic X.com verbs for the agent (ADR 0001).

Every verb: one JSON envelope on stdout, human log on stderr, exit code
0/1/2/3. One Chrome tab per invocation, closed on exit.
"""

import argparse
import sys

from . import envelope, failure, read, session, write


def _positive_int(v: str) -> int:
    i = int(v)
    if i < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return i


def main(argv: list[str] | None = None) -> None:
    failure.flush_pending()
    p = argparse.ArgumentParser(prog="x",
                                description="X.com action CLI for the agent")
    sub = p.add_subparsers(dest="verb", required=True)

    s = sub.add_parser("session", help="verify the X session on the agent Chrome")
    s.add_argument("--json", action="store_true", help="emit evidence JSON")

    st = sub.add_parser("status", help="read posts: text + stats (likes, views...); "
                                       "several URLs share one tab and return items[]")
    st.add_argument("url", nargs="+")

    n = sub.add_parser("notifications", help="read the notifications feed")
    n.add_argument("--limit", type=_positive_int, default=20,
                   help="max notifications to return (default 20)")

    t = sub.add_parser("thread", help="read a thread: focal post + replies")
    t.add_argument("url")

    pr = sub.add_parser("profile", help="read a profile: counts + timeline (best effort)")
    pr.add_argument("handle")

    sw = sub.add_parser("sweep", help="observation sweep: for each handle, only posts "
                                      "younger than --since (age from the snowflake ID)")
    sw.add_argument("handles", nargs="+")
    sw.add_argument("--since", type=_positive_int, default=180,
                    help="freshness window in minutes (default 180)")
    sw.add_argument("--pace", type=float, default=10.0,
                    help="min seconds between navigations (default 10)")
    sw.add_argument("--rounds", type=_positive_int, default=2,
                    help="scroll rounds per profile (default 2)")

    rp2 = sub.add_parser("replies", help="target vetting: how often HANDLE answers other "
                                          "accounts (with_replies timeline, last 7 days)")
    rp2.add_argument("handle")

    an = sub.add_parser("analytics", help="Premium per-post analytics of OUR posts "
                                          "(impressions, engagements, detail expands, "
                                          "profile visits); several URLs share one tab")
    an.add_argument("url", nargs="+")

    def _media(sp):
        sp.add_argument("--media", nargs="*", default=[],
                        help="images from renders/ (render.py sidecar required), max 4")
        sp.add_argument("--model", default=None,
                        help="writing model tag for items.json (default $X_AGENT_MODEL)")

    r = sub.add_parser("reply", help="reply to a post; evidence or bug issue")
    r.add_argument("url")
    r.add_argument("--text", required=True)
    r.add_argument("--check", action="store_true",
                   help="run gates only, never submit")
    _media(r)

    po = sub.add_parser("post", help="publish an original post; evidence or bug issue")
    po.add_argument("--text", required=True)
    po.add_argument("--check", action="store_true",
                    help="run gates only, never submit")
    po.add_argument("--series", help="series tag for items.json (metrics|postmortem|take|…)")
    _media(po)

    q = sub.add_parser("quote", help="quote a post (retweet menu → Cita/Quote → composer)")
    q.add_argument("url")
    q.add_argument("--text", required=True)
    q.add_argument("--check", action="store_true", help="run gates only, never submit")
    q.add_argument("--series")
    _media(q)

    lk = sub.add_parser("like", help="like a post (cap 30/day); idempotent")
    lk.add_argument("url")
    lk.add_argument("--check", action="store_true", help="locate + cap check, never click")

    rp = sub.add_parser("repost", help="repost a post (cap 2/day); idempotent")
    rp.add_argument("url")
    rp.add_argument("--check", action="store_true", help="open the menu, verify, never confirm")

    fo = sub.add_parser("follow", help="follow an account (Floor: 3/day, reason required)")
    fo.add_argument("handle")
    fo.add_argument("--reason", required=True, help="why (follow-back, replied to us, …)")
    fo.add_argument("--check", action="store_true", help="locate + cap check, never click")

    d = sub.add_parser("delete", help="recall (delete) one of our posts; no cap, "
                                      "closes its items.json row")
    d.add_argument("url")
    d.add_argument("--check", action="store_true",
                   help="open the menu, verify the item, never confirm")

    b = sub.add_parser("bio", help="set the account bio; evidence or bug issue")
    b.add_argument("--text", required=True)
    b.add_argument("--check", action="store_true",
                   help="run gates only, never submit")

    pn = sub.add_parser("pin", help="pin one of our posts to the profile")
    pn.add_argument("url")
    pn.add_argument("--check", action="store_true",
                    help="run gates only, never submit")

    args = p.parse_args(argv)

    if args.verb == "session":
        try:
            cdp = session.open_tab("https://x.com/home", "session")
            try:
                state = session.who_am_i(cdp)
            finally:
                cdp.close()
        except SystemExit:
            raise
        except Exception as e:
            envelope.fail("session", envelope.INFRA, "session-probe-failed",
                          f"{type(e).__name__}: {e}")
        if state["login_btn"] or not state["authed"]:
            envelope.fail("session", envelope.SESSION, "session-lost",
                          "X session lost — owner login needed on the Pi",
                          diagnostics=state)
        if state["handle"] != session.OWNER_HANDLE:
            envelope.fail("session", envelope.SESSION, "wrong-session",
                          f"logged in as @{state['handle']}",
                          diagnostics=state)
        envelope.log(f"session ok: @{state['handle']}")
        envelope.emit("session", state)

    try:
        if args.verb == "status":
            read.status(args.url)
        elif args.verb == "notifications":
            read.notifications(limit=args.limit)
        elif args.verb == "thread":
            read.thread(args.url)
        elif args.verb == "profile":
            read.profile(args.handle.lstrip("@"))
        elif args.verb == "sweep":
            read.sweep([h.lstrip("@") for h in args.handles], since_min=args.since,
                       pace=args.pace, rounds=args.rounds)
        elif args.verb == "analytics":
            read.analytics(args.url)
        elif args.verb == "replies":
            read.replies(args.handle.lstrip("@"))
        elif args.verb == "reply":
            write.reply(args.url, args.text, check_only=args.check, media=args.media, model=args.model)
        elif args.verb == "post":
            write.post(args.text, check_only=args.check, media=args.media,
                       series=args.series, model=args.model)
        elif args.verb == "quote":
            write.quote(args.url, args.text, check_only=args.check, media=args.media,
                        series=args.series, model=args.model)
        elif args.verb == "like":
            write.like(args.url, check_only=args.check)
        elif args.verb == "repost":
            write.repost(args.url, check_only=args.check)
        elif args.verb == "follow":
            write.follow(args.handle, args.reason, check_only=args.check)
        elif args.verb == "delete":
            write.delete(args.url, check_only=args.check)
        elif args.verb == "bio":
            write.bio(args.text, check_only=args.check)
        elif args.verb == "pin":
            write.pin(args.url, check_only=args.check)
    except SystemExit:
        raise
    except Exception as e:  # unexpected: still honor the contract
        envelope.fail(args.verb, envelope.BUG, "unexpected-exception",
                      f"{type(e).__name__}: {e}",
                      diagnostics={"argv": sys.argv[1:]})


if __name__ == "__main__":
    main()
