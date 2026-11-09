"""
Norynth File Organizer Pro - application entry point.

    python app.py                  # desktop app (pywebview + HTML UI)
    python app.py --cli --source X --dest Y [--dry-run] [...]   # scripted use

Both paths require a valid license and both use engine.py for all file work.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import subprocess
import sys
import threading
import traceback
import webbrowser
from dataclasses import asdict

import engine
from engine import APP_NAME, APP_VERSION, Cancelled, Engine, Options

WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"
SUPPORT_EMAIL = "support@norynth.com"
MAX_ROWS_TO_UI = 5000


# --------------------------------------------------------------------------- #
# Native helpers (no tkinter needed)
# --------------------------------------------------------------------------- #
def message_box(title: str, text: str, yes_no: bool = False) -> bool:
    """Show a native message box. Returns True for OK/Yes."""
    if os.name == "nt":
        import ctypes
        flags = 0x00000004 | 0x00000020 if yes_no else 0x00000010   # YESNO+ICONQUESTION / ICONERROR
        return ctypes.windll.user32.MessageBoxW(0, text, title, flags) in (1, 6)
    print(f"{title}\n{text}", file=sys.stderr)
    return False


def webview2_installed() -> bool:
    """True if the Microsoft Edge WebView2 runtime is present (always True off Windows)."""
    if os.name != "nt":
        return True
    try:
        import winreg
    except ImportError:
        return True
    guid = r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for hive, sub in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node" + guid[8:]),
                      (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE" + guid[8:]),
                      (winreg.HKEY_CURRENT_USER, guid)):
        try:
            with winreg.OpenKey(hive, sub) as k:
                version, _ = winreg.QueryValueEx(k, "pv")
                if version and version != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


def license_state() -> dict:
    """Ask license_check for the current state (never raises)."""
    try:
        import license_check
        ok, msg = license_check.validate_license()
        return {"valid": bool(ok), "order": msg if ok else "", "reason": "" if ok else msg}
    except Exception as e:  # missing module, broken build...
        return {"valid": False, "order": "", "reason": f"license module error: {e}"}


def require_license() -> None:
    st = license_state()
    if st["valid"]:
        return
    message_box("Norynth File Organizer - License Required",
                f"No valid license was found.\n\nReason: {st['reason']}\n\n"
                f"Place license.key in the same folder as the application.\n\nSupport: {SUPPORT_EMAIL}")
    sys.exit(1)


def open_path(path: str) -> None:
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


# --------------------------------------------------------------------------- #
# JS API
# --------------------------------------------------------------------------- #
def safe(fn):
    """Return {'ok': False, 'error': ...} instead of letting exceptions reach the UI."""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            res = fn(*a, **kw)
            return res if isinstance(res, dict) and "ok" in res else {"ok": True, "data": res}
        except (ValueError, Cancelled) as e:
            return {"ok": False, "error": str(e) or "Cancelled"}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return wrapper


class Api:
    """Everything public here is callable from JavaScript as pywebview.api.<name>().
    All state is stored in underscore attributes so pywebview does not try to expose it."""

    def __init__(self) -> None:
        self._engine = Engine()
        self._window = None
        self._plans: dict = {}
        self._job_lock = threading.Lock()
        self._job_name = None
        self._cancel = threading.Event()

    # ---- plumbing ---------------------------------------------------------
    def _emit(self, kind: str, payload: dict) -> None:
        if self._window is None:
            return
        try:
            self._window.evaluate_js(f"window.NOR && window.NOR.emit({json.dumps(kind)},{json.dumps(payload)})")
        except Exception:
            pass

    def _start_job(self, name: str, work) -> dict:
        """Run work(progress, cancel) in a thread; results come back through events."""
        require_license()
        if not self._job_lock.acquire(blocking=False):
            return {"ok": False, "error": f"Another task is running ({self._job_name})."}
        self._job_name = name
        self._cancel.clear()

        def progress(stage, done, total, message):
            self._emit("progress", {"job": name, "stage": stage, "done": done, "total": total, "message": message})

        def runner():
            try:
                result = work(progress, self._cancel)
                self._emit("done", {"job": name, "ok": True, "result": result})
            except Cancelled:
                self._emit("done", {"job": name, "ok": False, "cancelled": True, "error": "Cancelled"})
            except Exception as e:
                traceback.print_exc()
                self._emit("done", {"job": name, "ok": False, "error": f"{type(e).__name__}: {e}"})
            finally:
                self._job_name = None
                self._job_lock.release()

        threading.Thread(target=runner, daemon=True).start()
        return {"ok": True}

    # ---- app state --------------------------------------------------------
    @safe
    def bootstrap(self):
        e = self._engine
        return {
            "app": APP_NAME, "version": APP_VERSION, "platform": sys.platform,
            "license": license_state(), "settings": e.settings, "rules": e.rules,
            "presets": [{"name": p["name"], "description": p.get("description", ""), "strategy": p.get("strategy", "")}
                        for p in e.presets.get("presets", [])],
            "deps": [{"name": k, "ok": v[0], "error": v[1]} for k, v in engine.DEPS.items()],
            "data_dir": str(e.data_dir), "support": SUPPORT_EMAIL, "home": os.path.expanduser("~"),
        }

    @safe
    def save_settings(self, settings):
        return self._engine.save_settings(settings or {})

    @safe
    def save_rules(self, rules):
        return self._engine.save_rules(rules or [])

    # ---- dialogs / OS -----------------------------------------------------
    @safe
    def pick_folder(self, title="Choose a folder"):
        import webview
        kind = webview.FileDialog.FOLDER if hasattr(webview, "FileDialog") else webview.FOLDER_DIALOG
        res = self._window.create_file_dialog(kind)
        return res[0] if res else None

    @safe
    def resolve_folder(self, path):
        path = str(path or "")
        if os.path.isfile(path):
            path = os.path.dirname(path)
        return path if os.path.isdir(path) else None

    @safe
    def open_path(self, path):
        if not path or not os.path.exists(path):
            raise ValueError("That location no longer exists.")
        open_path(path)

    @safe
    def open_data_dir(self):
        open_path(str(self._engine.data_dir))

    @safe
    def open_webview2_page(self):
        webbrowser.open(WEBVIEW2_URL)

    # ---- jobs -------------------------------------------------------------
    @safe
    def start_plan(self, options):
        opts = Options.from_dict(options)
        Engine.validate(opts)

        def work(progress, cancel):
            plan = self._engine.plan(opts, progress, cancel)
            self._plans = {plan["id"]: plan}          # keep only the latest plan in memory
            shown = plan["items"][:MAX_ROWS_TO_UI]
            return {"id": plan["id"], "items": shown, "truncated": len(plan["items"]) > len(shown),
                    "summary": plan["summary"], "options": plan["options"]}
        return self._start_job("plan", work)

    @safe
    def start_execute(self, plan_id, excluded_ids):
        plan = self._plans.get(plan_id)
        if not plan:
            raise ValueError("This preview has expired. Please run the preview again.")
        return self._start_job("execute", lambda progress, cancel:
                               self._engine.execute(plan, excluded_ids or [], progress, cancel))

    @safe
    def start_undo(self, run_id):
        return self._start_job("undo", lambda progress, cancel: self._engine.undo(run_id, progress, cancel))

    @safe
    def start_dup_scan(self, folders, recursive=True):
        folders = [f for f in (folders or []) if f]
        if not folders:
            raise ValueError("Add at least one folder to scan.")
        return self._start_job("dups", lambda progress, cancel:
                               self._engine.find_duplicates(folders, bool(recursive), progress, cancel))

    @safe
    def start_quarantine(self, paths, base):
        if not paths:
            raise ValueError("Nothing selected.")
        return self._start_job("quarantine", lambda progress, cancel:
                               self._engine.quarantine(list(paths), base, progress))

    @safe
    def cancel_job(self):
        self._cancel.set()

    # ---- history ----------------------------------------------------------
    @safe
    def history(self):
        return self._engine.history()

    @safe
    def history_detail(self, run_id):
        return self._engine.run_ops(run_id)

    @safe
    def delete_run(self, run_id):
        self._engine.delete_run(run_id)

    @safe
    def export_report(self, run_id):
        import webview
        kind = webview.FileDialog.SAVE if hasattr(webview, "FileDialog") else webview.SAVE_DIALOG
        res = self._window.create_file_dialog(kind, save_filename=f"norynth-report-{run_id}.csv")
        if not res:
            return {"ok": True, "data": None}
        path = res if isinstance(res, str) else res[0]
        return {"ok": True, "data": {"path": path, "rows": self._engine.export_report(run_id, path)}}


# --------------------------------------------------------------------------- #
# Desktop app
# --------------------------------------------------------------------------- #
def run_gui() -> int:
    require_license()
    if not webview2_installed():
        if message_box(
                "Microsoft Edge WebView2 required",
                "Norynth File Organizer needs the free Microsoft Edge WebView2 runtime.\n\n"
                "Open the Microsoft download page now?", yes_no=True):
            webbrowser.open(WEBVIEW2_URL)
        return 1
    try:
        import webview
    except Exception as e:
        message_box("Norynth File Organizer", f"The UI component failed to load:\n{e}")
        return 1

    api = Api()
    window = webview.create_window(
        f"{APP_NAME}", url=str(engine.resource_path("ui/index.html")), js_api=api,
        width=1320, height=860, min_size=(1040, 700), background_color="#0b0e14")
    api._window = window

    def on_loaded():
        # Best effort: drag & drop of folders from Explorer (needs pywebview's DOM events).
        try:
            from webview.dom import DOMEventHandler

            def on_drop(event):
                files = event.get("dataTransfer", {}).get("files", [])
                if files and files[0].get("pywebviewFullPath"):
                    api._emit("dropped", {"path": files[0]["pywebviewFullPath"]})
            window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
        except Exception:
            pass

    window.events.loaded += on_loaded
    webview.start(debug="--debug" in sys.argv)
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def run_cli(argv) -> int:
    p = argparse.ArgumentParser(prog="app.py --cli", description=f"{APP_NAME} - command line")
    p.add_argument("--cli", action="store_true")
    p.add_argument("--source", "-s", required=True)
    p.add_argument("--dest", "-d", required=True)
    p.add_argument("--strategy", choices=["type", "date", "extracted-date", "content", "size"], default="type")
    p.add_argument("--preset", "-p", default="")
    p.add_argument("--copy", action="store_true")
    p.add_argument("--no-rename", action="store_true")
    p.add_argument("--no-rules", action="store_true")
    p.add_argument("--keep-duplicates", action="store_true", help="do not skip duplicate files")
    p.add_argument("--recursive", "-r", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="show what would happen, change nothing")
    args = p.parse_args(argv)

    require_license()
    eng = Engine()
    opts = Options(source=args.source, dest=args.dest, strategy=args.strategy, preset=args.preset,
                   use_rules=not args.no_rules, recursive=args.recursive, copy_mode=args.copy,
                   smart_rename=not args.no_rename, skip_duplicates=not args.keep_duplicates)
    try:
        plan = eng.plan(opts)
    except ValueError as e:
        print(f"[ERROR] {e}")
        return 1
    s = plan["summary"]
    print(f"{s['ready']} to {'copy' if args.copy else 'move'}, {s['duplicate']} duplicates skipped, "
          f"{s['inplace']} already in place, {s['error']} errors ({engine.format_size(s['size_ready'])})")
    for it in plan["items"]:
        if it["status"] == "ready":
            print(f"  {it['src_name']}  ->  {it['rel']}")
    if args.dry_run:
        print("Dry run - nothing was changed.")
        return 0
    res = eng.execute(plan)
    print(f"Done: {res['done']} processed, {res['errors']} errors. Run id: {res['id']} (undo from the History page)")
    return 0 if res["errors"] == 0 else 2


if __name__ == "__main__":
    if "--cli" in sys.argv:
        sys.exit(run_cli(sys.argv[1:]))
    sys.exit(run_gui())
