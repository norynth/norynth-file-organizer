# Norynth File Organizer

**Local-first desktop file organization for Windows. No cloud. No subscriptions. Nothing leaves your machine.**

> **Buy:** €49 — download now, license key by email. [Product page](https://www.norynth.com/products/ai-tools/) · [PayPal](https://www.paypal.com/ncp/payment/BGZX2W5FJL89S)

---

## What it does

Pick a folder, click Preview, see exactly what will move where, untick anything you want to leave alone, then Apply. Every run is undoable, even after restarting the app. Nothing is deleted — extras are moved to a reversible quarantine.

- **Date detection** — extracts dates from common filename formats (e.g. `2024-03-15`, `20240315`) and photo EXIF metadata
- **Content classification** — reads inside PDFs, DOCX and text files to categorize by keyword
- **Rules builder** — conditions on type, filename, regex, text content, size and age; folder templates like `Finance/{year}/{month}`
- **5 built-in presets** — Invoices, Photos, Projects, Documents, Code
- **Duplicate handling** — content-hash comparison, including against the destination. Duplicates are skipped when organizing; the Duplicates page moves extras to a reversible quarantine folder.
- **Full undo** — every run is written to disk and reversible from History
- **Batch processing** — thousands of files with progress and Cancel
- **Offline** — the app makes no network connections

Ships as a single Windows `.exe`. PDFs, images, DOCX and plain text supported. Requires WebView2 (included with Windows 11 and most Windows 10 systems; the app offers to download it if missing).

## License

Commercial desktop software, **proprietary — Norynth**. Each copy is licensed per customer via an Ed25519 license key emailed after purchase. The source is published here for transparency and archival, not for redistribution.

## Building from source

Requirements: Python 3.12, Windows 10/11.

```bat
cd src
py -3.12 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python app.py
```

To build the distributable exe:

```bat
python build_exe.py
```

The exe is written to `dist\Norynth_File_Organizer.exe`. Place a valid `license.key` next to the exe to run it outside a development environment.

## Source layout

| Path | Purpose |
|---|---|
| `src/app.py` | Application entry point, pywebview window, license gate |
| `src/engine.py` | File organization logic: preview, move/copy, undo, rules, duplicates |
| `src/ui/index.html` | Entire UI in one offline HTML file |
| `src/license_check.py` | Ed25519 license verification (public key only) |
| `src/presets.json` | Built-in rule presets |
| `src/build_exe.py` | PyInstaller packaging script |
| `src/test_engine.py` | Engine unit tests |

## Support

support@norynth.com

---

© Norynth. All rights reserved.
