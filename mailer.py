"""
Contact-form mailer: emails each new Contact Us message to the site's inbox.

The dashboard has no internet access (deploy/compose.yaml), so it only saves each message to
.messages.jsonl in the runs volume. This small process runs beside it with that volume mounted
read-only, and forwards every message it has not sent yet to the 365soft email worker, which
sends it through Microsoft 365. Standard library only.

The recipient, sender and template are fixed here; visitors supply only the form fields, so this
can never send mail anywhere but MAIL_TO.

Environment
  CF_ACCESS_CLIENT_ID / CF_ACCESS_CLIENT_SECRET   Cloudflare Access service token for the worker
  MAIL_API_URL     default https://365soft-email-worker.nick-598.workers.dev/api/send
  MAIL_TO          default hello@qtumdynamics.com
  MAIL_FROM        default hello@qtumdynamics.com
  MSG_FILE         default /runs/.messages.jsonl
  STATE_FILE       default /state/sent.json (ids already sent or given up on)
  POLL_SECONDS     default 20
"""
import html
import json
import os
import re
import time
import urllib.error
import urllib.request

API = os.environ.get("MAIL_API_URL", "https://365soft-email-worker.nick-598.workers.dev/api/send")
TO = os.environ.get("MAIL_TO", "hello@qtumdynamics.com")
FROM = os.environ.get("MAIL_FROM", "hello@qtumdynamics.com")
MSG_FILE = os.environ.get("MSG_FILE", "/runs/.messages.jsonl")
STATE_FILE = os.environ.get("STATE_FILE", "/state/sent.json")
POLL = int(os.environ.get("POLL_SECONDS", "20"))
CID = os.environ.get("CF_ACCESS_CLIENT_ID", "").strip()
CSECRET = os.environ.get("CF_ACCESS_CLIENT_SECRET", "").strip()
MAX_TRIES = 10  # with the back-off below, about 8 hours of retrying


def log(msg):
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime()) + msg, flush=True)


def one_line(s, n=120):
    """For the subject: no control characters, so nothing can be smuggled into a header."""
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(s)).strip()[:n]


def esc(s):
    # html.escape, plus braces: the worker fills in {{merge_tags}}, and a visitor's text must stay text
    return html.escape(str(s)).replace("{", "&#123;").replace("}", "&#125;")


def body(m):
    row = lambda k, v: (f'<tr><td style="padding:8px 12px;font-weight:600;border-bottom:1px solid #e2e8f0;'
                        f'vertical-align:top;">{k}</td><td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;">{v}</td></tr>')
    email = esc(m.get("email", ""))
    return ('<div style="font:15px Arial,sans-serif;color:#0f172a;max-width:620px;">'
            '<p style="margin:0 0 14px;">New message from the Contact Us form on qtumdynamics.com.</p>'
            '<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;margin:0 0 16px;">'
            + row("Name", esc(m.get("name", "")))
            + row("Email", f'<a href="mailto:{email}">{email}</a>')
            + row("Organisation", esc(m.get("organisation", "")) or "&mdash;")
            + row("Sent", esc(m.get("time", "")) + " UTC")
            + '</table><div style="white-space:pre-wrap;line-height:1.6;padding:14px;background:#f8fafc;'
            f'border-radius:8px;">{esc(m.get("message", ""))}</div>'
            f'<p style="margin:16px 0 0;color:#64748b;font-size:13px;">To reply, write to {email}. '
            f'Message id {esc(m.get("id", ""))}.</p></div>')


def send(m):
    data = json.dumps({"to": TO, "fromEmail": FROM, "contentType": "HTML",
                       "subject": one_line("Contact form: " + m.get("name", "")),
                       "message": body(m), "respectUnsubscribe": False}).encode()
    req = urllib.request.Request(API, data=data, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": "qtumdynamics-mailer/1.0",
        "CF-Access-Client-Id": CID, "CF-Access-Client-Secret": CSECRET})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code} {e.read(200).decode(errors='replace')}"
    except Exception as e:  # network trouble: try again next round
        return False, type(e).__name__ + ": " + str(e)[:200]


def read_messages():
    if not os.path.exists(MSG_FILE):
        return []
    out = []
    with open(MSG_FILE, encoding="utf-8") as fh:
        for line in fh:
            try:
                m = json.loads(line)
                if m.get("id"):
                    out.append(m)
            except ValueError:
                pass
    return out


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            return set(json.load(fh))
    except (OSError, ValueError):
        return None


def save_state(done):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(sorted(done), fh)
    os.replace(tmp, STATE_FILE)


def main():
    if not (CID and CSECRET):
        log("CF_ACCESS_CLIENT_ID / CF_ACCESS_CLIENT_SECRET not set; not sending")
        while True:
            time.sleep(3600)
    done = load_state()
    if done is None:  # first start: messages from before the mailer existed stay in /admin only
        done = {m["id"] for m in read_messages()}
        save_state(done)
        log(f"first start: {len(done)} earlier message(s) left in /admin, not emailed")
    tries = {}
    log(f"watching {MSG_FILE}, sending to {TO}")
    while True:
        wait = POLL
        for m in read_messages():
            if m["id"] in done:
                continue
            ok, why = send(m)
            if ok:
                done.add(m["id"])
                log(f"sent {m['id']}")
            else:
                tries[m["id"]] = tries.get(m["id"], 0) + 1
                log(f"failed {m['id']} (try {tries[m['id']]}): {why}")
                if tries[m["id"]] >= MAX_TRIES:
                    done.add(m["id"])
                    log(f"gave up on {m['id']}; it is still in /admin")
                else:
                    wait = min(60 * 2 ** (tries[m["id"]] - 1), 3600)  # back off: 1, 2, 4 ... 60 min
                    break
            save_state(done)
        time.sleep(wait)


if __name__ == "__main__":
    main()
