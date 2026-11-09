"""
Norynth File Organizer - engine.

All file logic lives here and has NO UI dependency, so the HTML app, the CLI and
the tests all use the exact same code path:

    plan()                 -> dry run: decide where every file would go, touch nothing
    execute()              -> carry out a plan, record every operation in history
    undo()                 -> reverse a recorded run
    find_duplicates()      -> content-based duplicate groups
    quarantine()           -> move chosen duplicates to a reversible quarantine folder
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

APP_NAME = "Norynth File Organizer"
APP_VERSION = "1.0"
QUARANTINE_DIR = "_Duplicates"

# --------------------------------------------------------------------------- #
# Optional dependencies. The real import error is kept so Settings can show it.
# --------------------------------------------------------------------------- #
DEPS: Dict[str, Tuple[bool, str]] = {}
fitz = docx = piexif = PILImage = None  # type: ignore


def _load_optional() -> None:
    global fitz, docx, piexif, PILImage
    try:
        import pymupdf as _fitz  # type: ignore
        fitz = _fitz
        DEPS["PyMuPDF (PDF text)"] = (True, "")
    except Exception as e1:
        try:
            import fitz as _fitz  # type: ignore
            fitz = _fitz
            DEPS["PyMuPDF (PDF text)"] = (True, "")
        except Exception as e2:
            DEPS["PyMuPDF (PDF text)"] = (False, f"{type(e2).__name__}: {e2}")
    try:
        import docx as _docx  # type: ignore
        if not hasattr(_docx, "Document"):
            raise ImportError("wrong 'docx' package installed - use python-docx")
        docx = _docx
        DEPS["python-docx (DOCX text)"] = (True, "")
    except Exception as e:
        DEPS["python-docx (DOCX text)"] = (False, f"{type(e).__name__}: {e}")
    try:
        import piexif as _piexif  # type: ignore
        piexif = _piexif
        DEPS["piexif (EXIF dates)"] = (True, "")
    except Exception as e:
        DEPS["piexif (EXIF dates)"] = (False, f"{type(e).__name__}: {e}")
    try:
        from PIL import Image as _img  # type: ignore
        PILImage = _img
        DEPS["Pillow (images)"] = (True, "")
    except Exception as e:
        DEPS["Pillow (images)"] = (False, f"{type(e).__name__}: {e}")


_load_optional()

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

def app_data_dir() -> Path:
    override = os.environ.get("NORYNTH_DATA_DIR")
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Norynth" / "FileOrganizer"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Norynth" / "FileOrganizer"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "norynth" / "file-organizer"
    base.mkdir(parents=True, exist_ok=True)
    return base


def resource_path(rel: str) -> Path:
    """Path to a bundled resource (works from source and from a PyInstaller exe)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / rel


# --------------------------------------------------------------------------- #
# Static tables
# --------------------------------------------------------------------------- #
CATEGORIES = {
    "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico", ".heic", ".tif", ".tiff", ".raw", ".cr2", ".nef", ".arw"],
    "Videos": [".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm"],
    "Audio": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"],
    "Documents": [".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".md"],
    "Spreadsheets": [".xls", ".xlsx", ".csv", ".ods"],
    "Presentations": [".ppt", ".pptx", ".key", ".odp"],
    "Archives": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"],
    "Code": [".py", ".js", ".ts", ".html", ".css", ".java", ".cpp", ".c", ".h", ".cs", ".php", ".rb", ".go", ".rs", ".sh", ".ps1"],
    "Executables": [".exe", ".msi", ".app", ".dmg", ".deb", ".rpm"],
    "Data": [".json", ".xml", ".yaml", ".yml", ".sql", ".db", ".sqlite"],
}
EXT_TO_CATEGORY = {e: c for c, exts in CATEGORIES.items() for e in exts}

CONTENT_PATTERNS = {
    "Work": ["report", "meeting", "presentation", "invoice", "contract", "project"],
    "Personal": ["photo", "vacation", "family", "birthday", "wedding"],
    "Finance": ["receipt", "tax", "bank", "statement", "invoice", "payment", "balance", "digest"],
    "Education": ["course", "lecture", "homework", "assignment", "study", "notes"],
    "Entertainment": ["movie", "game", "music", "video", "show", "episode"],
    "Downloads": ["download", "temp", "new", "untitled"],
}

TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".xml", ".log", ".py", ".js", ".html", ".css", ".java",
             ".cpp", ".c", ".php", ".rb", ".go", ".rs"}

STOPWORDS = set("""high low best top new more most very good great the and for with from this that your our all any
can will has have was are not but you its about into over also using use used her one out day get him his how may now
old see two who boy did she way they know want been much some time when come here just like long make many such take
than them well were""".split())

LANGUAGES = {".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".java": "Java", ".cpp": "C++", ".c": "C",
             ".h": "C", ".cs": "C#", ".php": "PHP", ".rb": "Ruby", ".go": "Go", ".rs": "Rust", ".sh": "Shell",
             ".ps1": "PowerShell", ".html": "Web", ".css": "Web"}

SKIP_NAMES = {"desktop.ini", "thumbs.db", ".ds_store"}
TEMP_SUFFIXES = (".tmp", ".crdownload", ".part", ".partial", ".download")
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_ILLEGAL = re.compile(r'[<>:"|?*\x00-\x1f]')

DEFAULT_SETTINGS = {
    "enable_content_extraction": True,
    "enable_exif_dates": True,
    "enable_filename_dates": True,
    "max_content_scan_kb": 512,
    "theme": "dark",
    "last_options": {},
}

ProgressCB = Callable[[str, int, int, str], None]


class Cancelled(Exception):
    pass


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def clean_component(part: str) -> str:
    part = _ILLEGAL.sub("_", part).strip().rstrip(". ")
    if not part:
        return "_"
    if part.split(".")[0].upper() in RESERVED:
        part = "_" + part
    return part


def clean_rel_path(rel: str) -> str:
    parts = [clean_component(p) for p in re.split(r"[\\/]+", rel) if p and p not in (".", "..")]
    return "/".join(parts)


def _split_list(value) -> List[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        value = ",".join(map(str, value))
    return [x.strip().lower().lstrip(".") for x in re.split(r"[,;\n]", str(value)) if x.strip()]


def _num(v) -> Optional[float]:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def unique_path(path: str, taken: Optional[set] = None) -> str:
    taken = taken if taken is not None else set()

    def busy(p: str) -> bool:
        return os.path.exists(p) or os.path.normcase(p) in taken

    if not busy(path):
        return path
    base, ext = os.path.splitext(path)
    n = 1
    while busy(f"{base}_{n}{ext}"):
        n += 1
    return f"{base}_{n}{ext}"


def file_hash(path: str, quick: bool = False) -> Optional[str]:
    h = hashlib.blake2b(digest_size=20)
    try:
        with open(path, "rb") as f:
            if quick:
                h.update(f.read(65536))
            else:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def format_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _inside(child: str, parent: str) -> bool:
    try:
        c, p = os.path.normcase(os.path.abspath(child)), os.path.normcase(os.path.abspath(parent))
        return os.path.commonpath([c, p]) == p
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# Options
# --------------------------------------------------------------------------- #
@dataclass
class Options:
    source: str = ""
    dest: str = ""
    strategy: str = "type"        # type | date | extracted-date | content | size
    preset: str = ""              # preset name from presets.json
    use_rules: bool = True        # apply the user's custom rules first
    recursive: bool = False
    copy_mode: bool = False
    smart_rename: bool = True
    skip_duplicates: bool = True
    skip_hidden: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "Options":
        known = {f.name for f in fields(cls)}
        o = cls(**{k: v for k, v in (d or {}).items() if k in known})
        for b in ("use_rules", "recursive", "copy_mode", "smart_rename", "skip_duplicates", "skip_hidden"):
            setattr(o, b, bool(getattr(o, b)))
        return o


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
class Engine:
    def __init__(self) -> None:
        self.data_dir = app_data_dir()
        self.runs_dir = self.data_dir / "history"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.settings = self._load_json(self.data_dir / "settings.json", {})
        for k, v in DEFAULT_SETTINGS.items():
            self.settings.setdefault(k, v)
        self.rules: List[dict] = self._load_json(self.data_dir / "rules.json", [])
        self.presets: dict = self._load_presets()
        self._text_cache: Dict[str, str] = {}
        self._date_cache: Dict[str, Tuple[datetime, bool]] = {}

    # ---- persistence ------------------------------------------------------
    @staticmethod
    def _load_json(path: Path, default):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    @staticmethod
    def _save_json(path: Path, data) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)

    def _load_presets(self) -> dict:
        user = self.data_dir / "presets.json"
        for p in (user, resource_path("presets.json")):
            data = self._load_json(p, None)
            if isinstance(data, dict) and data.get("presets"):
                return data
        return {"presets": [], "settings": {}}

    def save_settings(self, new: dict) -> dict:
        for k in DEFAULT_SETTINGS:
            if k in new:
                self.settings[k] = new[k]
        try:
            self.settings["max_content_scan_kb"] = max(16, min(int(self.settings["max_content_scan_kb"]), 8192))
        except (TypeError, ValueError):
            self.settings["max_content_scan_kb"] = 512
        self._save_json(self.data_dir / "settings.json", self.settings)
        return self.settings

    def save_rules(self, rules: List[dict]) -> List[dict]:
        cleaned = []
        for r in rules or []:
            cleaned.append({
                "id": r.get("id") or uuid.uuid4().hex[:8],
                "name": str(r.get("name") or "Untitled rule")[:80],
                "enabled": bool(r.get("enabled", True)),
                "ext": r.get("ext", ""), "name_contains": r.get("name_contains", ""),
                "name_regex": r.get("name_regex", ""), "content_contains": r.get("content_contains", ""),
                "min_mb": r.get("min_mb", ""), "max_mb": r.get("max_mb", ""),
                "older_days": r.get("older_days", ""), "newer_days": r.get("newer_days", ""),
                "dest": str(r.get("dest") or "{type}"),
            })
        self.rules = cleaned
        self._save_json(self.data_dir / "rules.json", cleaned)
        return cleaned

    # ---- dates & content --------------------------------------------------
    @staticmethod
    def date_from_filename(filepath: str) -> Optional[datetime]:
        name = os.path.splitext(os.path.basename(filepath))[0]
        patterns = [
            (r'(\d{4})[-_](\d{2})[-_](\d{2})[-_ ]?(\d{2})?[-_:]?(\d{2})?[-_:]?(\d{2})?', True),
            (r'(\d{2})[-_](\d{2})[-_](\d{4})[-_ ]?(\d{2})?[-_:]?(\d{2})?[-_:]?(\d{2})?', False),
            (r'(\d{4})(\d{2})(\d{2})[-_ ]?(\d{2})?(\d{2})?(\d{2})?', True),
        ]
        for pattern, year_first in patterns:
            m = re.search(pattern, name)
            if not m:
                continue
            g = m.groups()
            try:
                if year_first:
                    y, mo, d = int(g[0]), int(g[1]), int(g[2])
                else:
                    d, mo, y = int(g[0]), int(g[1]), int(g[2])
                hh, mm, ss = (int(x) if x else 0 for x in g[3:6])
                if 1900 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
                    return datetime(y, mo, d, hh, mm, ss)
            except ValueError:
                continue
        return None

    @staticmethod
    def date_from_exif(filepath: str) -> Optional[datetime]:
        if piexif is None or os.path.splitext(filepath)[1].lower() not in (".jpg", ".jpeg", ".tif", ".tiff"):
            return None
        try:
            exif = piexif.load(filepath)
            for ifd, tag in (("Exif", piexif.ExifIFD.DateTimeOriginal), ("Exif", piexif.ExifIFD.DateTimeDigitized),
                             ("0th", piexif.ImageIFD.DateTime)):
                if tag in exif.get(ifd, {}):
                    return datetime.strptime(exif[ifd][tag].decode("utf-8"), "%Y:%m:%d %H:%M:%S")
        except Exception:
            pass
        return None

    def best_date(self, filepath: str) -> Tuple[datetime, bool]:
        """filename date > EXIF date > modification time. Returns (date, has_real_time)."""
        if filepath in self._date_cache:
            return self._date_cache[filepath]
        result: Optional[Tuple[datetime, bool]] = None
        if self.settings["enable_filename_dates"]:
            d = self.date_from_filename(filepath)
            if d:
                result = (d, bool(d.hour or d.minute or d.second))
        if result is None and self.settings["enable_exif_dates"]:
            d = self.date_from_exif(filepath)
            if d:
                result = (d, bool(d.hour or d.minute or d.second))
        if result is None:
            try:
                result = (datetime.fromtimestamp(os.path.getmtime(filepath)), False)
            except OSError:
                result = (datetime.now(), False)
        self._date_cache[filepath] = result
        return result

    def text_of(self, filepath: str) -> str:
        if not self.settings["enable_content_extraction"]:
            return ""
        if filepath in self._text_cache:
            return self._text_cache[filepath]
        ext = os.path.splitext(filepath)[1].lower()
        limit = int(self.settings["max_content_scan_kb"]) * 1024
        text = ""
        try:
            if ext == ".pdf" and fitz is not None:
                with fitz.open(filepath) as doc:
                    parts, n = [], 0
                    for page in doc:
                        t = page.get_text()
                        parts.append(t)
                        n += len(t)
                        if n >= limit:
                            break
                    text = "".join(parts)[:limit]
            elif ext == ".docx" and docx is not None:
                d = docx.Document(filepath)
                text = "\n".join(p.text for p in d.paragraphs)[:limit]
            elif ext in TEXT_EXTS:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read(limit)
        except Exception:
            text = ""
        self._text_cache[filepath] = text
        return text

    def keywords_of(self, filepath: str, limit: int = 10) -> List[str]:
        text = self.text_of(filepath)
        out, seen = [], set()
        for w in re.findall(r"\b[A-Za-z]{3,}\b", text):
            lw = w.lower()
            if lw not in STOPWORDS and lw not in seen:
                seen.add(lw)
                out.append(w)
                if len(out) >= limit:
                    break
        return out

    # ---- categorisation ---------------------------------------------------
    @staticmethod
    def category_by_type(filepath: str) -> str:
        return EXT_TO_CATEGORY.get(os.path.splitext(filepath)[1].lower(), "Other")

    @staticmethod
    def size_class(size: int) -> str:
        if size < 100 * 1024:
            return "Small (0-100KB)"
        if size < 10 * 1024 * 1024:
            return "Medium (100KB-10MB)"
        if size < 100 * 1024 * 1024:
            return "Large (10MB-100MB)"
        return "Very Large (100MB+)"

    def category_by_content(self, filepath: str) -> str:
        name = os.path.basename(filepath).lower()
        for cat, words in CONTENT_PATTERNS.items():
            if any(w in name for w in words):
                return cat
        text = self.text_of(filepath).lower()
        if text:
            for cat, words in CONTENT_PATTERNS.items():
                if any(w in text for w in words):
                    return cat
        return self.category_by_type(filepath)

    def categorize(self, filepath: str, strategy: str, size: int, mtime: float) -> str:
        if strategy == "type":
            return self.category_by_type(filepath)
        if strategy == "date":
            d = datetime.fromtimestamp(mtime)
            return f"{d.year}/{d.strftime('%m-%B')}"
        if strategy == "extracted-date":
            d, _ = self.best_date(filepath)
            return f"{d.year}/{d.strftime('%m-%B')}"
        if strategy == "content":
            return self.category_by_content(filepath)
        if strategy == "size":
            return self.size_class(size)
        return "Uncategorized"

    # ---- templates, rules, presets ---------------------------------------
    TOKEN_ALIASES = {"date_year": "year", "date_month": "month", "date_day": "day",
                     "category": "type", "original_name": "name"}

    def render_template(self, tpl: str, filepath: str, size: int, mtime: float) -> str:
        stem, ext = os.path.splitext(os.path.basename(filepath))
        cache: Dict[str, str] = {}

        def getter(key: str) -> str:
            if key in cache:
                return cache[key]
            if key in ("year", "month", "month_name", "day", "date"):
                d, _ = self.best_date(filepath)
                vals = {"year": f"{d.year}", "month": f"{d.month:02d}", "month_name": d.strftime("%B"),
                        "day": f"{d.day:02d}", "date": d.strftime("%Y-%m-%d")}
                cache.update(vals)
                return vals[key]
            if key == "type":
                v = self.category_by_type(filepath)
            elif key == "ext":
                v = ext.lstrip(".").lower() or "none"
            elif key == "name":
                v = stem
            elif key == "size_class":
                v = self.size_class(size)
            elif key == "language":
                v = LANGUAGES.get(ext.lower(), "Other")
            elif key == "project_name":
                m = re.search(r"(?i)(?:project|proj)[-_\s]([a-z0-9]+)", stem)
                v = m.group(1) if m else ""
            else:
                v = ""
            cache[key] = v
            return v

        def rep(m: "re.Match") -> str:
            key = self.TOKEN_ALIASES.get(m.group(1).lower(), m.group(1).lower())
            return getter(key) or "General"

        return clean_rel_path(re.sub(r"\{(\w+)\}", rep, tpl))

    def rule_matches(self, rule: dict, filepath: str, size: int, mtime: float) -> bool:
        name = os.path.basename(filepath)
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        checks = 0
        exts = _split_list(rule.get("ext"))
        if exts:
            checks += 1
            if ext not in exts:
                return False
        words = _split_list(rule.get("name_contains"))
        if words:
            checks += 1
            if not any(w in name.lower() for w in words):
                return False
        rx = (rule.get("name_regex") or "").strip()
        if rx:
            checks += 1
            try:
                if not re.search(rx, name, re.I):
                    return False
            except re.error:
                return False
        lo, hi = _num(rule.get("min_mb")), _num(rule.get("max_mb"))
        if lo is not None:
            checks += 1
            if size < lo * 1024 * 1024:
                return False
        if hi is not None:
            checks += 1
            if size > hi * 1024 * 1024:
                return False
        age = (time.time() - mtime) / 86400
        older, newer = _num(rule.get("older_days")), _num(rule.get("newer_days"))
        if older is not None:
            checks += 1
            if age < older:
                return False
        if newer is not None:
            checks += 1
            if age > newer:
                return False
        content = _split_list(rule.get("content_contains"))
        if content:
            checks += 1
            text = self.text_of(filepath).lower()
            if not text or not any(w in text for w in content):
                return False
        return checks > 0   # a rule with no conditions never matches

    def preset_by_name(self, name: str) -> Optional[dict]:
        for p in self.presets.get("presets", []):
            if p.get("name") == name:
                return p
        return None

    def preset_matches(self, preset: dict, filepath: str) -> bool:
        name = os.path.basename(filepath)
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        for pat in preset.get("patterns", []):
            t = pat.get("type")
            try:
                if t == "filename" and re.search(pat.get("pattern", ""), name):
                    return True
                if t == "extension" and re.fullmatch(pat.get("pattern", ""), ext):
                    return True
                if t == "exif" and self.date_from_exif(filepath):
                    return True
                if t == "content":
                    text = self.text_of(filepath).lower()
                    if text and any(k.lower() in text for k in pat.get("keywords", [])):
                        return True
            except re.error:
                continue
        return False

    def destination_for(self, filepath: str, opts: Options, size: int, mtime: float) -> Tuple[str, str]:
        """Return (relative folder, label of what decided it)."""
        if opts.use_rules:
            for rule in self.rules:
                if rule.get("enabled", True) and self.rule_matches(rule, filepath, size, mtime):
                    return self.render_template(rule.get("dest") or "{type}", filepath, size, mtime), f"Rule: {rule.get('name')}"
        strategy = opts.strategy
        if opts.preset:
            preset = self.preset_by_name(opts.preset)
            if preset:
                strategy = preset.get("strategy", strategy)
                tpl = preset.get("destination_template")
                if tpl and self.preset_matches(preset, filepath):
                    return self.render_template(tpl, filepath, size, mtime), f"Preset: {preset['name']}"
        return clean_rel_path(self.categorize(filepath, strategy, size, mtime)) or "Other", f"Strategy: {strategy}"

    def smart_name(self, filepath: str) -> str:
        original = os.path.basename(filepath)
        name, ext = os.path.splitext(original)
        best, has_time = self.best_date(filepath)
        parts = [best.strftime("%Y%m%d")]
        if has_time:
            parts.append(best.strftime("%H%M%S"))
        for pat in (r"\d{4}[-_]?\d{2}[-_]?\d{2}", r"\d{2}[-_]?\d{2}[-_]?\d{4}",
                    r"\d{2}[-_:]?\d{2}[-_:]?\d{2}", r"(?<![0-9])\d{4}(?![0-9])"):
            name = re.sub(pat, "", name)
        name = re.sub(r"[-_]{2,}", "_", name)
        name = re.sub(r"[^\w\s-]", "", name)
        name = re.sub(r"[-\s]+", "_", name).strip("_-")
        keywords = self.keywords_of(filepath) if self.settings["enable_content_extraction"] else []
        if keywords and keywords[0].lower() not in name.lower():
            parts.append(keywords[0])
        if name and len(name) > 2:
            parts.append(name[:50])
        elif not keywords:
            parts.append("file")
        return "_".join(parts)[:100] + ext

    # ---- planning (dry run) ----------------------------------------------
    @staticmethod
    def validate(opts: Options) -> None:
        if not opts.source or not os.path.isdir(opts.source):
            raise ValueError("Source folder does not exist.")
        if not opts.dest:
            raise ValueError("Please choose a destination folder.")
        if os.path.exists(opts.dest) and not os.path.isdir(opts.dest):
            raise ValueError("Destination is not a folder.")

    def _collect(self, opts: Options, cancel: Optional[threading.Event], progress: Optional[ProgressCB]):
        src, dest = os.path.abspath(opts.source), os.path.abspath(opts.dest)
        prune_dest = os.path.normcase(dest) != os.path.normcase(src) and _inside(dest, src)
        out = []

        def accept(name: str) -> bool:
            low = name.lower()
            if low in SKIP_NAMES or low.endswith(TEMP_SUFFIXES):
                return False
            return not (opts.skip_hidden and name.startswith("."))

        def add(path: str) -> None:
            try:
                st = os.stat(path)
                out.append((path, st.st_size, st.st_mtime))
            except OSError:
                pass

        if opts.recursive:
            for root, dirs, files in os.walk(src):
                if cancel and cancel.is_set():
                    raise Cancelled()
                dirs[:] = [d for d in dirs
                           if not (opts.skip_hidden and d.startswith(".")) and d != QUARANTINE_DIR
                           and not (prune_dest and os.path.normcase(os.path.join(root, d)) == os.path.normcase(dest))]
                for f in files:
                    if accept(f):
                        add(os.path.join(root, f))
                if progress:
                    progress("scan", len(out), 0, f"Scanning... {len(out)} files")
        else:
            for entry in os.scandir(src):
                if entry.is_file(follow_symlinks=False) and accept(entry.name):
                    add(entry.path)
        return out

    def plan(self, opts: Options, progress: Optional[ProgressCB] = None,
             cancel: Optional[threading.Event] = None) -> dict:
        self.validate(opts)
        self._text_cache.clear()
        self._date_cache.clear()
        dest_root = os.path.abspath(opts.dest)
        files = self._collect(opts, cancel, progress)

        # Duplicate detection index: sizes of everything in the destination too.
        size_counts: Counter = Counter(s for _, s, _ in files if s > 0)
        dest_by_size: Dict[int, List[str]] = {}
        if opts.skip_duplicates and os.path.isdir(dest_root):
            for root, _, names in os.walk(dest_root):
                for n in names:
                    p = os.path.join(root, n)
                    try:
                        s = os.path.getsize(p)
                    except OSError:
                        continue
                    if s > 0:
                        dest_by_size.setdefault(s, []).append(p)
                        size_counts[s] += 1
        hash_cache: Dict[str, Optional[str]] = {}
        seen: Dict[str, str] = {}

        def hashed(p: str) -> Optional[str]:
            if p not in hash_cache:
                hash_cache[p] = file_hash(p)
            return hash_cache[p]

        def duplicate_of(p: str, size: int) -> Optional[str]:
            if size <= 0 or size_counts[size] < 2:
                return None
            h = hashed(p)
            if not h:
                return None
            if h in seen:
                return seen[h]
            for other in dest_by_size.get(size, []):
                if os.path.normcase(other) != os.path.normcase(p) and hashed(other) == h:
                    return other
            seen[h] = p
            return None

        items, taken = [], set()
        total = len(files)
        for i, (fp, size, mtime) in enumerate(files):
            if cancel and cancel.is_set():
                raise Cancelled()
            if progress and (i % 20 == 0 or i == total - 1):
                progress("plan", i + 1, total, f"Analysing {os.path.basename(fp)}")
            item = {"id": i, "src": fp, "src_name": os.path.basename(fp), "size": size,
                    "action": "copy" if opts.copy_mode else "move", "status": "ready",
                    "note": "", "dest": "", "rel": "", "folder": "", "rule": ""}
            try:
                if opts.skip_duplicates:
                    dup = duplicate_of(fp, size)
                    if dup:
                        item.update(status="duplicate", note=f"Identical to {dup}")
                        items.append(item)
                        continue
                folder, label = self.destination_for(fp, opts, size, mtime)
                name = self.smart_name(fp) if opts.smart_rename else os.path.basename(fp)
                name = clean_component(name)
                target = os.path.abspath(os.path.join(dest_root, *folder.split("/"), name))
                if not _inside(target, dest_root):
                    raise ValueError("Destination escapes the target folder")
                item.update(folder=folder, rule=label)
                if os.path.normcase(target) == os.path.normcase(os.path.abspath(fp)):
                    item.update(status="inplace", note="Already in the right place", dest=target)
                else:
                    final = unique_path(target, taken)
                    if final != target:
                        item["note"] = "Renamed to avoid a name clash"
                    taken.add(os.path.normcase(final))
                    item.update(dest=final, rel=os.path.relpath(final, dest_root).replace("\\", "/"))
            except Cancelled:
                raise
            except Exception as e:
                item.update(status="error", note=str(e))
            items.append(item)

        summary = {
            "total": len(items),
            "ready": sum(1 for x in items if x["status"] == "ready"),
            "duplicate": sum(1 for x in items if x["status"] == "duplicate"),
            "inplace": sum(1 for x in items if x["status"] == "inplace"),
            "error": sum(1 for x in items if x["status"] == "error"),
            "size_ready": sum(x["size"] for x in items if x["status"] == "ready"),
            "folders": dict(Counter(x["folder"] for x in items if x["status"] == "ready").most_common(12)),
        }
        return {"id": uuid.uuid4().hex[:10], "options": asdict(opts), "items": items, "summary": summary,
                "created": time.time()}

    # ---- execution --------------------------------------------------------
    def _new_run(self, kind: str, **extra) -> dict:
        run = {"id": time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4], "kind": kind, "ts": time.time(),
               "status": "running", "undone": False, "total": 0, "done": 0, "errors": 0, "skipped": 0,
               "ops": [], "error_list": []}
        run.update(extra)
        return run

    def _save_run(self, run: dict) -> None:
        meta = {k: v for k, v in run.items() if k not in ("ops", "error_list")}
        meta["error_sample"] = run["error_list"][:20]
        self._save_json(self.runs_dir / f"{run['id']}.meta.json", meta)
        self._save_json(self.runs_dir / f"{run['id']}.ops.json", run["ops"])

    def execute(self, plan: dict, excluded: Iterable[int] = (), progress: Optional[ProgressCB] = None,
                cancel: Optional[threading.Event] = None) -> dict:
        opts = Options.from_dict(plan["options"])
        excluded = set(excluded)
        todo = [it for it in plan["items"] if it["status"] == "ready" and it["id"] not in excluded]
        run = self._new_run("organize", source=opts.source, dest=opts.dest, strategy=opts.strategy,
                            mode="copy" if opts.copy_mode else "move", total=len(todo),
                            skipped=len(plan["items"]) - len(todo))
        try:
            for i, it in enumerate(todo):
                if cancel and cancel.is_set():
                    run["status"] = "cancelled"
                    break
                if progress:
                    progress("execute", i, len(todo), f"{'Copying' if opts.copy_mode else 'Moving'} {it['src_name']}")
                try:
                    if not os.path.exists(it["src"]):
                        raise FileNotFoundError("source file no longer exists")
                    target = it["dest"]
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    if os.path.exists(target):
                        target = unique_path(target)
                    if opts.copy_mode:
                        shutil.copy2(it["src"], target)
                    else:
                        shutil.move(it["src"], target)
                    run["ops"].append({"src": it["src"], "dest": target, "action": it["action"]})
                    run["done"] += 1
                except Exception as e:
                    run["errors"] += 1
                    run["error_list"].append(f"{it['src_name']}: {e}")
            else:
                run["status"] = "completed"
            if run["status"] == "running":
                run["status"] = "completed"
        finally:
            if run["status"] == "running":
                run["status"] = "interrupted"
            self._save_run(run)
        if progress:
            progress("execute", len(todo), len(todo), "Done")
        return {k: v for k, v in run.items() if k not in ("ops",)}

    # ---- undo -------------------------------------------------------------
    def undo(self, run_id: str, progress: Optional[ProgressCB] = None,
             cancel: Optional[threading.Event] = None) -> dict:
        meta_path = self.runs_dir / f"{run_id}.meta.json"
        meta = self._load_json(meta_path, None)
        if not meta:
            raise ValueError("Run not found.")
        if meta.get("undone"):
            raise ValueError("This run was already undone.")
        ops = self._load_json(self.runs_dir / f"{run_id}.ops.json", [])
        restored = removed = missing = failed = 0
        dest_root = meta.get("dest")
        dirs_touched = set()
        for i, op in enumerate(reversed(ops)):
            if cancel and cancel.is_set():
                break
            if progress:
                progress("undo", i, len(ops), f"Restoring {os.path.basename(op['src'])}")
            try:
                if not os.path.exists(op["dest"]):
                    missing += 1
                    continue
                dirs_touched.add(os.path.dirname(op["dest"]))
                if op["action"] == "copy":
                    os.remove(op["dest"])
                    removed += 1
                else:
                    target = op["src"]
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    if os.path.exists(target):
                        target = unique_path(target)
                    shutil.move(op["dest"], target)
                    restored += 1
            except Exception:
                failed += 1
        # tidy up folders we emptied (never the destination root itself)
        for d in sorted(dirs_touched, key=len, reverse=True):
            cur = d
            while dest_root and _inside(cur, dest_root) and os.path.normcase(cur) != os.path.normcase(os.path.abspath(dest_root)):
                try:
                    os.rmdir(cur)
                except OSError:
                    break
                cur = os.path.dirname(cur)
        done_all = (restored + removed + missing + failed) == len(ops)
        if done_all:
            meta["undone"] = True
            meta["status"] = "undone"
            meta["undone_ts"] = time.time()
            self._save_json(meta_path, meta)
        return {"restored": restored, "removed": removed, "missing": missing, "failed": failed, "complete": done_all}

    # ---- history ----------------------------------------------------------
    def history(self) -> List[dict]:
        out = []
        for p in self.runs_dir.glob("*.meta.json"):
            m = self._load_json(p, None)
            if m:
                out.append(m)
        out.sort(key=lambda m: m.get("ts", 0), reverse=True)
        return out

    def run_ops(self, run_id: str, limit: int = 500) -> dict:
        ops = self._load_json(self.runs_dir / f"{run_id}.ops.json", [])
        return {"ops": ops[:limit], "total": len(ops)}

    def delete_run(self, run_id: str) -> None:
        for suffix in (".meta.json", ".ops.json"):
            try:
                os.remove(self.runs_dir / f"{run_id}{suffix}")
            except OSError:
                pass

    def export_report(self, run_id: str, path: str) -> int:
        meta = self._load_json(self.runs_dir / f"{run_id}.meta.json", {})
        ops = self._load_json(self.runs_dir / f"{run_id}.ops.json", [])
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["action", "from", "to", "run", "date"])
            when = datetime.fromtimestamp(meta.get("ts", 0)).strftime("%Y-%m-%d %H:%M:%S")
            for op in ops:
                w.writerow([op["action"], op["src"], op["dest"], run_id, when])
        return len(ops)

    # ---- duplicates -------------------------------------------------------
    def find_duplicates(self, folders: List[str], recursive: bool = True, progress: Optional[ProgressCB] = None,
                        cancel: Optional[threading.Event] = None) -> List[dict]:
        by_size: Dict[int, List[str]] = {}
        seen_paths = set()
        n = 0
        for folder in folders:
            if not os.path.isdir(folder):
                continue
            walker = os.walk(folder) if recursive else [(folder, [], [e.name for e in os.scandir(folder) if e.is_file()])]
            for root, dirs, names in walker:
                if cancel and cancel.is_set():
                    raise Cancelled()
                dirs[:] = [d for d in dirs if d != QUARANTINE_DIR]
                for name in names:
                    p = os.path.join(root, name)
                    key = os.path.normcase(os.path.abspath(p))
                    if key in seen_paths or name.lower() in SKIP_NAMES:
                        continue
                    seen_paths.add(key)
                    try:
                        s = os.path.getsize(p)
                    except OSError:
                        continue
                    if s > 0:
                        by_size.setdefault(s, []).append(p)
                        n += 1
                if progress:
                    progress("scan", n, 0, f"Scanning... {n} files")
        candidates = [(s, ps) for s, ps in by_size.items() if len(ps) > 1]
        total = sum(len(ps) for _, ps in candidates)
        groups, done = [], 0
        for size, paths in candidates:
            quick: Dict[str, List[str]] = {}
            for p in paths:
                if cancel and cancel.is_set():
                    raise Cancelled()
                done += 1
                if progress and done % 10 == 0:
                    progress("hash", done, total, f"Comparing {os.path.basename(p)}")
                q = file_hash(p, quick=True)
                if q:
                    quick.setdefault(q, []).append(p)
            for same in quick.values():
                if len(same) < 2:
                    continue
                full: Dict[str, List[str]] = {}
                for p in same:
                    h = file_hash(p)
                    if h:
                        full.setdefault(h, []).append(p)
                for h, ps in full.items():
                    if len(ps) > 1:
                        files = []
                        for p in ps:
                            try:
                                files.append({"path": p, "mtime": os.path.getmtime(p), "size": size})
                            except OSError:
                                pass
                        if len(files) > 1:
                            groups.append({"hash": h, "size": size, "files": files, "wasted": size * (len(files) - 1)})
        groups.sort(key=lambda g: g["wasted"], reverse=True)
        return groups

    def quarantine(self, paths: List[str], base: str, progress: Optional[ProgressCB] = None) -> dict:
        qdir = os.path.join(os.path.abspath(base), QUARANTINE_DIR)
        run = self._new_run("duplicates", source=base, dest=qdir, strategy="duplicates", mode="move", total=len(paths))
        try:
            os.makedirs(qdir, exist_ok=True)
            for i, p in enumerate(paths):
                if progress:
                    progress("execute", i, len(paths), f"Moving {os.path.basename(p)}")
                try:
                    target = unique_path(os.path.join(qdir, clean_component(os.path.basename(p))))
                    shutil.move(p, target)
                    run["ops"].append({"src": p, "dest": target, "action": "move"})
                    run["done"] += 1
                except Exception as e:
                    run["errors"] += 1
                    run["error_list"].append(f"{os.path.basename(p)}: {e}")
            run["status"] = "completed"
        finally:
            if run["status"] == "running":
                run["status"] = "interrupted"
            self._save_run(run)
        return {k: v for k, v in run.items() if k != "ops"}
