# Changelog

All notable changes to Norynth File Organizer are documented here.

## [1.0] — 2026-11-09

First public release. Windows `.exe`, licensed per customer.

### Added

- **pywebview desktop UI** — single offline HTML interface with sidebar navigation (Organize, Rules, Duplicates, History, Settings, About), dark/light theme, progress panel with Cancel, and per-file untick in the preview table
- **Engine** — preview/move/copy, disk-backed undo across restarts, content-hash duplicate detection (including against the destination)
- **Rules builder** — conditions on type, filename, regex, content text, size, age; folder templates like `Finance/{year}/{month}`
- **5 built-in presets** — Invoices, Photos, Projects, Documents, Code
- **Date detection** — common filename formats plus photo EXIF metadata
- **Content classification** — reads PDFs (PyMuPDF), DOCX (python-docx), and plain text
- **Per-customer Ed25519 license keys** — offline verification, no network call; license enforced on every operation
- **PyInstaller one-file Windows build** — WebView2 required (included with Windows 11 and most Windows 10 systems; the app offers a download link if missing)

### Known limitations

- Scanned PDFs (image-only) are not OCR'd
