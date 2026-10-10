"""Save a finished session for the learning loop: state, result with trace, back office, every
e-mail of every thread and every attachment (raw file and its text)."""

import json
from pathlib import Path

from arena_kit import ArenaError
from arena_kit.docs import read_document

LOGS = Path("logs/sessions")


def save(client, session_id, probe=None, root=LOGS):
    """Write <root>/<set>/<case>_<sid>.json and the attachments into <case>_<sid>/. Returns the
    JSON path, or None while the trace is not out yet (final: after the final)."""
    state = client.session(session_id)
    if state["status"] != "ended" or not (state.get("result") or {}).get("trace"):
        return None
    stem = f"{state['case_id'].split(':')[-1]}_{session_id}"
    out = root / state["set"]
    files = out / stem
    files.mkdir(parents=True, exist_ok=True)
    try:
        state["backoffice"] = client.backoffice(session_id)
    except ArenaError:
        state["backoffice"] = None
    state["messages"] = {s: client.thread(session_id, s)["messages"] for s in state["threads"]}
    for messages in state["messages"].values():
        for m in messages:
            for att in m.get("attachments") or []:
                if not att.get("attachment_id"):
                    continue
                data = client.attachment(session_id, att["attachment_id"])
                (files / att["name"]).write_bytes(data)
                att["text"] = read_document(att["name"], data)
    if probe is not None:
        state["probe"] = probe
    path = out / f"{stem}.json"
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    return path


def pull(client, set_, root=LOGS):
    """Save every ended session of a set that is not saved yet."""
    saved = 0
    for s in client.sessions(set_):
        if (
            s["status"] == "ended"
            and not (root / set_ / f"{s['case_id'].split(':')[-1]}_{s['session_id']}.json").exists()
        ):
            saved += save(client, s["session_id"], root=root) is not None
    print(f"{saved} new sessions in {root / set_}")
