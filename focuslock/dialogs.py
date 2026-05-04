"""User-facing prompts.

The interactive prompts (ask_reason / ask_override / ask_off_topic /
show_result) are rendered by the Swift app as a styled SwiftUI floating
panel — far nicer than the native osascript box. This module is the Python
side of that IPC: write a `prompt.json`, block until Swift drops a
matching `response.json` next to it.

Notifications (show_notification) and the override-wrong toast stay on
osascript — they don't need to be pretty and they shouldn't block.
"""

import json
import os
import subprocess
import threading
import time
import uuid
from typing import Tuple

from .paths import PROMPT_PATH, RESPONSE_PATH

# Only one dialog at a time — multiple violations queue up rather than
# racing on prompt.json.
_prompt_lock = threading.Lock()
# Hard ceiling so a stuck Swift app doesn't pin a worker thread forever.
_PROMPT_TIMEOUT_SECONDS = 600


def _prompt(prompt: dict, timeout: int = _PROMPT_TIMEOUT_SECONDS) -> dict:
    """Write prompt, wait for matching response. Returns response dict or {} on timeout."""
    with _prompt_lock:
        pid = uuid.uuid4().hex
        prompt["id"] = pid

        # Drop any stale response left over from a crashed/killed Swift app.
        try:
            os.remove(RESPONSE_PATH)
        except FileNotFoundError:
            pass

        tmp = PROMPT_PATH + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(prompt, f)
            os.replace(tmp, PROMPT_PATH)
        except Exception as e:
            print(f"[Locus] prompt write failed: {e}")
            return {}

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with open(RESPONSE_PATH) as f:
                    resp = json.load(f)
                if resp.get("id") == pid:
                    try: os.remove(RESPONSE_PATH)
                    except FileNotFoundError: pass
                    try: os.remove(PROMPT_PATH)
                    except FileNotFoundError: pass
                    return resp
            except FileNotFoundError:
                pass
            except Exception:
                # Partial write or junk; ignore and keep polling.
                pass
            time.sleep(0.15)

        # Timeout — clean up the prompt so the next caller starts clean.
        try: os.remove(PROMPT_PATH)
        except FileNotFoundError: pass
        return {}


def ask_reason(
    blocked_name: str,
    blocked_type: str,   # "app" or "website"
    session_name: str,
) -> Tuple[str, str]:
    """Returns (action, reason). action ∈ {"submit", "override", "cancel"}."""
    resp = _prompt({
        "type": "ask_reason",
        "blocked_name": blocked_name,
        "blocked_type": blocked_type,
        "session_name": session_name,
    })
    action = resp.get("action") or "cancel"
    if action not in ("submit", "override", "cancel"):
        action = "cancel"
    return action, (resp.get("reason") or "").strip()


def ask_override_code(expected: str) -> bool:
    if not expected or not expected.strip():
        show_override_wrong()
        return False
    resp = _prompt({
        "type": "ask_override",
        "is_pi_hint": expected.startswith("3141592653589"),
    })
    if (resp.get("action") or "cancel") != "submit":
        return False
    entered = (resp.get("code") or "").strip()
    if expected.startswith("3141592653589") or expected.isdigit():
        cleaned = "".join(c for c in entered if c.isdigit())
        return cleaned == expected
    return entered == expected.strip()


def show_result(approved: bool, explanation: str, target_name: str, minutes: int = 15):
    _prompt({
        "type": "show_result",
        "approved": bool(approved),
        "explanation": explanation,
        "target_name": target_name,
        "minutes": int(minutes),
    })


def ask_off_topic_reason(
    domain: str,
    tab_title: str,
    session_name: str,
    ai_reason: str,
) -> Tuple[str, str]:
    resp = _prompt({
        "type": "ask_off_topic",
        "blocked_name": domain,
        "tab_title": tab_title,
        "session_name": session_name,
        "ai_reason": ai_reason,
    })
    action = resp.get("action") or "cancel"
    if action not in ("submit", "cancel"):
        action = "cancel"
    return action, (resp.get("reason") or "").strip()


def ask_long_session(session_name: str, timeout: int = 300) -> str:
    """Returns 'continue' or 'end'. Empty response (timeout) → 'end'."""
    resp = _prompt({
        "type": "long_session",
        "session_name": session_name,
    }, timeout=timeout)
    return "continue" if resp.get("action") == "continue" else "end"


# ── Non-interactive — stay on osascript ────────────────────────────────────

def _esc(s: str) -> str:
    out = str(s).replace("\\", "\\\\").replace('"', '\\"')
    for ch in ("\r\n", "\n", "\r", "¬"):
        out = out.replace(ch, " ")
    return out


def show_override_wrong():
    # Lightweight — a notification rather than a styled panel. The result
    # panel will follow if the user retries.
    show_notification("Locus", "Incorrect override code.")


def show_notification(title: str, message: str):
    script = f'display notification "{_esc(message)}" with title "{_esc(title)}"'
    subprocess.run(["osascript", "-e", script], capture_output=True)
