# Norynth File Organizer 1.0 (pywebview + HTML UI)

## What is in this folder
| File | Purpose |
|---|---|
| `engine.py` | All file logic (dry run, execute, undo, duplicates, rules, history). No UI code. |
| `app.py` | Desktop app: license gate, WebView2 check, bridge to the UI. Also the CLI (`--cli`). |
| `ui/index.html` | The whole interface (HTML + CSS + JS in one offline file). |
| `build_exe.py` | PyInstaller build with a package pre-check. |
| `requirements.txt`, `run.bat`, `presets.json` | As before (presets unchanged). |
| `test_engine.py` | Automated tests for the engine. |

Keep your existing `license_check.py` (with your real public key) in the same folder.
You can delete `file_organizer.py` and `modern_gui.py`; nothing uses them any more.

## Run from source (Windows PowerShell, in this folder)
    py -m pip install -r requirements.txt
    py app.py

## Build the exe
    py build_exe.py          # or: py build_exe.py onedir
Put `license.key` next to the exe. Settings, rules and history live in `%APPDATA%\Norynth\FileOrganizer`.

## WebView2
`app.py` checks for the runtime at start-up and offers to open Microsoft's download page if it is missing.
For your installer, follow Microsoft's WebView2 distribution guide and bundle the Evergreen bootstrapper
(it installs silently and does nothing if the runtime is already there).

## CLI (for scripts)
    py app.py --cli --source "C:\Users\me\Downloads" --dest "D:\Sorted" --recursive --dry-run
Needs a valid license too. The windowed exe has no console, so use this from source.

## Rules
Rules run top to bottom, first match wins. A rule matches when ALL its filled-in conditions are true.
Folder templates: {year} {month} {month_name} {day} {type} {ext} {name} {size_class} {language} {project_name}
(presets.json aliases such as {date_year} and {category} also work).
