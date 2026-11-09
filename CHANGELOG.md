# Changelog

## [1.0.0] — 2026-11-15

### Added
- Automated file organization: 5 strategies (type, date, extracted-date, content, size)
- Smart date detection from filenames (YYYY-MM-DD, DD-MM-YYYY, YYYYMMDD)
- Keyword-based content classification for PDF, DOCX, images, text
- Duplicate detection via MD5 hash
- Full undo of last operation
- 5 built-in rule presets (Invoices, Photos, Projects, Documents, Code)
- Headless CLI mode for batch processing thousands of files
- 100% local processing — no cloud, no uploads
- **Per-customer Ed25519 license keys** (offline verification, no network call)
- **License check at startup** — fails closed if no valid key

### Known limitations
- Scanned PDFs (image-only) not OCR'd
- License check is a speed bump, not copy protection (Python source can be decompiled)
