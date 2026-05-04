"""Locus — headless focus daemon. Launched by the Swift UI app."""

import json
import os
import signal
import threading
import time
from dataclasses import asdict
from typing import Optional, List

from .notion_client import NotionClient, NotionEvent
from .ical_client import ICalClient
from .claude_client import ClaudeClient
from .app_blocker import AppBlocker
from .url_monitor import URLMonitor
from .session import FocusSession
from . import dialogs
from .analytics import log_event, compute_summary
from .paths import CONFIG_PATH, STATE_PATH, COMMAND_PATH, ANALYTICS_PATH, LOCK_PATH


def load_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[config] {CONFIG_PATH} not found — using defaults")
        return {}
    except json.JSONDecodeError as e:
        print(f"[config] {CONFIG_PATH} is malformed ({e}) — using defaults")
        return {}


class FocusLockApp:
    def __init__(self):
        self.config = load_config()
        self._validate_config()

        self.notion: Optional[NotionClient] = None
        if self._notion_enabled():
            try:
                self.notion = NotionClient(
                    self.config["api_keys"]["notion"],
                    self.config.get("notion_database_id", ""),
                )
            except Exception as e:
                print(f"[Locus] Notion init failed: {e}")

        self.ical: Optional[ICalClient] = None
        self._init_ical()

        self.claude = ClaudeClient()

        self.app_blocker = AppBlocker(
            on_blocked=self._on_blocked_app,
            poll_seconds=self.config.get("app_poll_interval_seconds", 2),
            extra_always_allowed=self.config.get("always_allowed_apps", []),
        )
        self.url_monitor = URLMonitor(
            on_blocked_url=self._on_blocked_url,
            on_off_topic=self._on_off_topic_content,
            poll_seconds=self.config.get("url_poll_interval_seconds", 2),
            extra_always_allowed=self.config.get("always_allowed_domains", []),
        )
        self.debug_logging = bool(self.config.get("debug_logging", False))

        self.current_session: Optional[FocusSession] = None
        self._session_start_ts: Optional[float] = None
        self._long_session_warned: bool = False
        self._long_session_snooze_until: float = 0
        self.all_events: List[NotionEvent] = []

        self._refresh_schedule()
        threading.Thread(target=self._background_loop, daemon=True).start()
        threading.Thread(target=self._command_loop, daemon=True).start()

    def _validate_config(self):
        if self._notion_enabled():
            key = self.config.get("api_keys", {}).get("notion", "")
            if not key or key == "YOUR_NOTION_API_KEY":
                # Swift UI surfaces config problems visually; just log.
                print("[Locus] Notion is enabled but no API key is set.")

    def _init_ical(self):
        feeds_raw = self.config.get("ical_feeds") or []
        feeds: list = []
        for f in feeds_raw:
            if not isinstance(f, dict):
                continue
            url = (f.get("url") or "").strip()
            if not url:
                continue
            feeds.append((f.get("name", ""), url))
        if not feeds:
            self.ical = None
            return
        try:
            self.ical = ICalClient(feeds=feeds)
        except Exception as e:
            print(f"[Locus] iCal init failed: {e}")
            self.ical = None

    def _notion_enabled(self) -> bool:
        val = self.config.get("notion_enabled")
        if val is not None:
            return bool(val)
        # Legacy: if no flag, enable when a real key is present
        key = self.config.get("api_keys", {}).get("notion", "")
        return bool(key) and key != "YOUR_NOTION_API_KEY"

    # ── Schedule ──────────────────────────────────────────────────────────

    def _background_loop(self):
        refresh_secs = self.config.get("schedule_refresh_minutes", 5) * 60
        last_refresh = 0
        while True:
            if time.time() - last_refresh >= refresh_secs:
                self._refresh_schedule()
                last_refresh = time.time()
            else:
                self._write_state()
            self._write_analytics()
            self._maybe_warn_long_session()
            time.sleep(30)

    def _maybe_warn_long_session(self):
        if not self.current_session or not self._session_start_ts:
            return
        if self._long_session_warned:
            return
        if time.time() < self._long_session_snooze_until:
            return
        if time.time() - self._session_start_ts >= 5 * 3600:
            self._long_session_warned = True
            threading.Thread(target=self._run_long_session_dialog, daemon=True).start()

    def _run_long_session_dialog(self):
        session_name = self.current_session.display_name if self.current_session else "Focus Session"
        action = dialogs.ask_long_session(session_name, timeout=300)
        if action == "continue":
            self._long_session_warned = False
            self._long_session_snooze_until = time.time() + 3600
        else:
            self._end_session(None)

    def _refresh_schedule(self):
        events: List[NotionEvent] = []
        if self.notion is not None:
            try:
                events.extend(self.notion.get_upcoming_events())
            except Exception as e:
                print(f"[Locus] Notion fetch error: {e}")
        if self.ical is not None:
            try:
                events.extend(self.ical.get_upcoming_events())
            except Exception as e:
                print(f"[Locus] iCal fetch error: {e}")
        # Sort: by date, then by start_time (date-only events sort first).
        events.sort(key=lambda e: (e.date, e.start_time or ""))
        self.all_events = events
        print(f"[Locus] Loaded {len(self.all_events)} upcoming events")
        self._write_state()

    def _write_state(self):
        """Write events + session info for the Swift app to read."""
        state = {
            "events": [asdict(e) for e in self.all_events],
            "session": {
                "title": self.current_session.title,
                "class_name": self.current_session.class_name,
                "event_type": self.current_session.event_type,
                "display_name": self.current_session.display_name,
            } if self.current_session else None,
            "updated_at": time.time(),
        }
        tmp = STATE_PATH + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(state, f)
            os.replace(tmp, STATE_PATH)
        except Exception:
            pass

    def _write_analytics(self):
        try:
            summary = compute_summary()
            tmp = ANALYTICS_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump(summary, f)
            os.replace(tmp, ANALYTICS_PATH)
        except Exception:
            pass

    def _command_loop(self):
        """Watch for commands from the Swift app."""
        while True:
            if os.path.exists(COMMAND_PATH):
                try:
                    with open(COMMAND_PATH) as f:
                        cmd = json.load(f)
                    os.remove(COMMAND_PATH)
                    self._handle_command(cmd)
                except Exception:
                    try:
                        os.remove(COMMAND_PATH)
                    except FileNotFoundError:
                        pass
            time.sleep(0.3)

    def _handle_command(self, cmd: dict):
        cmd_type = cmd.get("type", "")
        data = cmd.get("data", {})
        if cmd_type == "start_session":
            # Prefer the stable (title, date) handle — index can shift if a
            # Notion refresh re-orders events between Swift sending the cmd
            # and us processing it. Fall back to index for older clients.
            handle_title = (data.get("title") or "").strip()
            handle_date = (data.get("date") or "").strip()
            event = None
            if handle_title and handle_date:
                event = next(
                    (e for e in self.all_events
                     if e.title == handle_title and e.date == handle_date),
                    None,
                )
            if event is None:
                idx = data.get("event_index", -1)
                if 0 <= idx < len(self.all_events):
                    event = self.all_events[idx]
            if event is not None:
                self._start_session(self._event_to_session(event))
        elif cmd_type == "start_custom_session":
            title = (data.get("title") or "").strip()
            if title:
                self._start_session(self._custom_session(title))
        elif cmd_type == "end_session":
            self._end_session(None)
        elif cmd_type == "refresh":
            self._refresh_schedule()
        elif cmd_type == "reconnect_ical":
            self.config = load_config()
            self._init_ical()
            self._refresh_schedule()
        elif cmd_type == "reconnect_notion":
            # Swift just changed the Notion key/db; rebuild the client so the
            # next refresh uses the new credentials instead of cached ones.
            self.config = load_config()
            try:
                if self._notion_enabled():
                    self.notion = NotionClient(
                        self.config["api_keys"]["notion"],
                        self.config.get("notion_database_id", ""),
                    )
                else:
                    self.notion = None
            except Exception as e:
                print(f"[Locus] Notion reconnect failed: {e}")
                self.notion = None
            self._refresh_schedule()

    def _custom_session(self, title: str) -> FocusSession:
        # Reload config so recent changes take effect
        self.config = load_config()
        activities = self.config.get("activities", {})
        mapping = activities.get("DEFAULT", {})
        return FocusSession(
            title=title,
            class_name=title,
            event_type="Task",
            open_apps=mapping.get("open_apps", []),
            allow_apps=mapping.get("allow_apps", []),
            allow_domains=mapping.get("allow_domains", []),
        )

    # ── Session control ───────────────────────────────────────────────────

    def _event_to_session(self, ev: NotionEvent) -> FocusSession:
        # Reload config so settings changes take effect without restart
        self.config = load_config()
        activities = self.config.get("activities", {})
        mapping = activities.get(ev.class_name) or activities.get("DEFAULT", {})
        return FocusSession(
            title=ev.title,
            class_name=ev.class_name or ev.title,
            event_type=ev.event_type,
            open_apps=mapping.get("open_apps", []),
            allow_apps=mapping.get("allow_apps", []),
            allow_domains=mapping.get("allow_domains", []),
        )

    def _start_session(self, session: FocusSession):
        self.current_session = session
        self._session_start_ts = time.time()
        self._long_session_warned = False
        self._long_session_snooze_until = 0
        try:
            log_event("session_start",
                      session_name=session.display_name,
                      title=session.title,
                      class_name=session.class_name,
                      event_type=session.event_type)
        except Exception:
            pass

        for app_name in session.open_apps:
            try:
                self.app_blocker.open_app(app_name)
            except Exception:
                pass

        self.app_blocker.set_session_allowed(session.allow_apps)
        self.app_blocker.session_name = session.display_name
        self.app_blocker.start()

        self.url_monitor.set_session_allowed_domains(session.allow_domains)
        self.url_monitor.session_name = session.display_name
        self.url_monitor.start()

        self._write_state()
        dialogs.show_notification("🔴 Locus Active", session.display_name)

    def _end_session(self, _):
        if not self.current_session:
            return
        session_name = self.current_session.display_name
        duration = int(time.time() - getattr(self, "_session_start_ts", time.time()))
        self.app_blocker.stop()
        self.url_monitor.stop()
        self.current_session = None
        self._session_start_ts = None
        try:
            log_event("session_end", session_name=session_name, duration_seconds=duration)
        except Exception:
            pass
        self._write_state()
        self._write_analytics()
        dialogs.show_notification("Locus", "Session ended. Nice work!")

    # ── Violation handlers ────────────────────────────────────────────────

    def _on_blocked_app(self, app_name: str):
        session_name = self.current_session.display_name if self.current_session else "Focus Session"
        try:
            log_event("app_blocked", app_name=app_name, session_name=session_name)
        except Exception:
            pass
        action, reason = dialogs.ask_reason(app_name, "app", session_name)

        if action == "cancel":
            self.app_blocker.deny(app_name)
            try:
                log_event("app_denied", app_name=app_name, reason="cancel",
                          session_name=session_name)
            except Exception:
                pass
            return

        if action == "override":
            if dialogs.ask_override_code(self.config.get("override_code", "")):
                mins = self.config.get("temporary_allow_minutes", 15)
                self.app_blocker.allow_temporarily(app_name, minutes=mins)
                self.app_blocker.open_app(app_name)
                dialogs.show_notification("Override accepted", f"{app_name} allowed for {mins} min")
                try:
                    log_event("app_allowed", app_name=app_name, reason="override",
                              session_name=session_name)
                except Exception:
                    pass
            else:
                dialogs.show_override_wrong()
                self.app_blocker.deny(app_name)
                try:
                    log_event("app_denied", app_name=app_name, reason="override_wrong",
                              session_name=session_name)
                except Exception:
                    pass
            return

        if not reason.strip():
            dialogs.show_result(False, "No reason provided.", app_name)
            self.app_blocker.deny(app_name)
            try:
                log_event("app_denied", app_name=app_name, reason="no_reason",
                          session_name=session_name)
            except Exception:
                pass
            return

        dialogs.show_notification("Locus", "Evaluating your reason…")
        approved, explanation = self.claude.evaluate_reason(
            subject=app_name, subject_type="app",
            session_name=session_name, reason=reason,
        )
        mins = self.config.get("temporary_allow_minutes", 15)
        dialogs.show_result(approved, explanation, app_name, minutes=mins)

        if approved:
            self.app_blocker.allow_temporarily(app_name, minutes=mins)
            self.app_blocker.open_app(app_name)
            try:
                log_event("app_allowed", app_name=app_name, reason="ai_approved",
                          session_name=session_name)
            except Exception:
                pass
        else:
            self.app_blocker.deny(app_name)
            try:
                log_event("app_denied", app_name=app_name, reason="ai_denied",
                          session_name=session_name)
            except Exception:
                pass

    def _on_blocked_url(self, domain: str, original_url: str, tab_id: Optional[int], tab_title: str = ""):
        session_name = self.current_session.display_name if self.current_session else "Focus Session"
        # `tab_title` is captured by url_monitor at the moment of detection,
        # so it reflects the actual blocked tab — not whichever window
        # happens to be frontmost when the AI pre-screen runs.

        # Smart pre-screen: check if the site is obviously relevant
        auto_allow, ai_reason = self.claude.evaluate_site_relevance(
            domain, session_name, tab_title,
        )
        if auto_allow:
            mins = self.config.get("temporary_allow_minutes", 15)
            self.url_monitor.allow_domain_temporarily(domain, minutes=mins)
            # url_monitor no longer pre-redirects on first sighting, so the
            # tab is still loading the original URL — nothing to restore.
            print(f"[FocusLock] Auto-allowed {domain}: {ai_reason}")
            try:
                log_event("url_allowed", domain=domain, reason="ai_approved",
                          session_name=session_name)
            except Exception:
                pass
            return

        # Check whether the user is still on the blocked tab before doing anything
        if tab_id:
            status = self.url_monitor.check_tab_status(tab_id)
            if status == "gone":
                return
            if status == "background":
                # User navigated away — silently close the blocked tab, no dialog
                self.url_monitor.close_tab_by_id(tab_id)
                try:
                    log_event("url_denied", domain=domain, reason="background_silent_close",
                              session_name=session_name)
                except Exception:
                    pass
                return
            # Active — blank the tab to about:blank and leave it there for
            # the duration of the dialog. If approved we navigate it back to
            # the original URL; if denied it stays on about:blank.
            self.url_monitor.redirect_tab_by_id(tab_id)
        else:
            # Fallback: no tab_id captured — fall back to old behavior
            self.url_monitor.redirect_chrome()

        # Pin the tab to about:blank while the dialog is up — this defeats
        # Chrome's back button: any navigation away (back/forward/reload)
        # gets snapped back to about:blank until the user answers.
        stop_pin = self.url_monitor.pin_tab_to_blank(tab_id) if tab_id else (lambda: None)
        try:
            action, reason = dialogs.ask_reason(domain, "website", session_name)
        finally:
            stop_pin()

        if action == "cancel":
            try:
                log_event("url_denied", domain=domain, reason="cancel",
                          session_name=session_name)
            except Exception:
                pass
            return

        if action == "override":
            if dialogs.ask_override_code(self.config.get("override_code", "")):
                mins = self.config.get("temporary_allow_minutes", 15)
                self.url_monitor.allow_domain_temporarily(domain, minutes=mins)
                self.url_monitor.set_title_cooldown(domain, seconds=7)
                if tab_id:
                    self.url_monitor.navigate_tab_by_id(tab_id, original_url)
                else:
                    self.url_monitor.navigate_chrome_to(original_url)
                dialogs.show_notification("Override accepted", f"{domain} allowed for {mins} min")
                try:
                    log_event("url_allowed", domain=domain, reason="override",
                              session_name=session_name)
                except Exception:
                    pass
            else:
                dialogs.show_override_wrong()
                try:
                    log_event("url_denied", domain=domain, reason="override_wrong",
                              session_name=session_name)
                except Exception:
                    pass
            return

        if not reason.strip():
            dialogs.show_result(False, "No reason provided.", domain)
            try:
                log_event("url_denied", domain=domain, reason="no_reason",
                          session_name=session_name)
            except Exception:
                pass
            return

        dialogs.show_notification("Locus", "Evaluating your reason…")
        approved, explanation = self.claude.evaluate_reason(
            subject=domain, subject_type="website",
            session_name=session_name, reason=reason,
        )
        mins = self.config.get("temporary_allow_minutes", 15)
        dialogs.show_result(approved, explanation, domain, minutes=mins)

        if approved:
            self.url_monitor.allow_domain_temporarily(domain, minutes=mins)
            self.url_monitor.set_title_cooldown(domain, seconds=10)
            if tab_id:
                self.url_monitor.navigate_tab_by_id(tab_id, original_url)
            else:
                self.url_monitor.navigate_chrome_to(original_url)
            try:
                log_event("url_allowed", domain=domain, reason="ai_approved",
                          session_name=session_name)
            except Exception:
                pass
        else:
            try:
                log_event("url_denied", domain=domain, reason="ai_denied",
                          session_name=session_name)
            except Exception:
                pass

    def _on_off_topic_content(self, domain: str, tab_title: str, tab_id: Optional[int]):
        """Called when a temporarily-allowed site shows potentially off-topic content."""
        session_name = self.current_session.display_name if self.current_session else "Focus Session"

        relevant, ai_reason = self.claude.evaluate_title(tab_title, session_name, domain)
        if relevant:
            return

        try:
            log_event("off_topic_detected", domain=domain, title=tab_title,
                      session_name=session_name)
        except Exception:
            pass

        # Check if user is still on the off-topic tab before taking action
        if tab_id:
            status = self.url_monitor.check_tab_status(tab_id)
            if status == "gone":
                self.url_monitor.temporarily_allowed.pop(domain, None)
                return
            if status == "background":
                # User moved on — just revoke + close that specific tab silently
                self.url_monitor.revoke_domain(domain, tab_id=tab_id)
                return

        # Off-topic detected and user is still there — revoke and reprompt
        self.url_monitor.revoke_domain(domain, tab_id=tab_id)

        action, user_reason = dialogs.ask_off_topic_reason(
            domain, tab_title, session_name, ai_reason,
        )

        if action == "cancel" or not user_reason.strip():
            return  # Already revoked, tab closed

        # Re-evaluate with the user's explanation
        dialogs.show_notification("Locus", "Evaluating your reason…")
        approved, explanation = self.claude.evaluate_reason(
            subject=f"{domain} — \"{tab_title}\"",
            subject_type="website content",
            session_name=session_name,
            reason=user_reason,
        )
        mins = self.config.get("temporary_allow_minutes", 15)
        dialogs.show_result(approved, explanation, domain, minutes=mins)

        if approved:
            self.url_monitor.allow_domain_temporarily(domain, minutes=mins)
            self.url_monitor.set_title_cooldown(domain, seconds=10)
            # The old tab was closed/blanked by revoke_domain() above, so open
            # a fresh tab instead of navigating the user's current tab (which
            # would be whatever window they switched to during the dialog).
            self.url_monitor.open_url_in_new_tab(f"https://{domain}")


def _acquire_single_instance_lock():
    """Ensure only one locusd is running.

    If another live process holds the lock, exit. If the lock file is stale
    (PID gone), take it over. Without this, multiple backends race on
    state.json and the UI flickers between session/no-session views.
    """
    try:
        os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
        if os.path.exists(LOCK_PATH):
            try:
                with open(LOCK_PATH) as f:
                    other_pid = int((f.read() or "0").strip())
            except Exception:
                other_pid = 0
            if other_pid and other_pid != os.getpid():
                try:
                    os.kill(other_pid, 0)  # signal 0 = liveness probe
                    print(f"[Locus] Another locusd is already running (pid {other_pid}); exiting.")
                    raise SystemExit(0)
                except ProcessLookupError:
                    pass  # stale lock — fall through and overwrite
                except PermissionError:
                    # Process exists but is owned by someone else; treat as live.
                    print(f"[Locus] locusd pid {other_pid} appears to be running; exiting.")
                    raise SystemExit(0)
        with open(LOCK_PATH, "w") as f:
            f.write(str(os.getpid()))
    except SystemExit:
        raise
    except Exception as e:
        print(f"[Locus] Lock acquisition failed (continuing): {e}")


def _release_lock():
    try:
        with open(LOCK_PATH) as f:
            owner = int((f.read() or "0").strip())
        if owner == os.getpid():
            os.remove(LOCK_PATH)
    except Exception:
        pass


def main():
    _acquire_single_instance_lock()
    app = FocusLockApp()  # noqa: F841 — worker threads run on it
    # Block forever; worker threads do all the work. SIGTERM / SIGINT exit.
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    try:
        stop.wait()
    finally:
        _release_lock()


if __name__ == "__main__":
    main()
