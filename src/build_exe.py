#!/usr/bin/env python3
"""
Build script for Norynth File Organizer Pro 2.x (pywebview + HTML UI).

    py -m pip install -r requirements.txt
    py build_exe.py            # single-file exe
    py build_exe.py onedir     # folder build (faster start, fewer antivirus false positives)
    py build_exe.py clean

Always run it with the SAME Python you installed the requirements into.
"""
import importlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REQUIRED = [  # (import name, pip name)
    ("PIL", "pillow"), ("pymupdf", "pymupdf"), ("docx", "python-docx"), ("piexif", "piexif"),
    ("cryptography", "cryptography"), ("webview", "pywebview"), ("PyInstaller", "pyinstaller"),
]
EXCLUDES = ["tkinter", "customtkinter", "darkdetect", "numpy", "scipy", "pandas", "matplotlib",
            "IPython", "pytest", "unittest", "doctest", "pydoc"]


def preflight() -> bool:
    print(f"Python: {sys.executable}")
    ok = True
    for mod, pip_name in REQUIRED:
        try:
            importlib.import_module(mod)
            print(f"  [OK]      {mod}")
        except Exception as e:
            ok = False
            print(f"  [MISSING] {mod} -> {sys.executable} -m pip install {pip_name}   ({e})")
    try:
        import docx
        if not hasattr(docx, "Document"):
            ok = False
            print("  [WRONG]   'docx' is the wrong package -> pip uninstall docx && pip install python-docx")
    except Exception:
        pass
    return ok


def build(onedir: bool = False) -> int:
    here = Path(__file__).parent.absolute()
    for needed in ("app.py", "engine.py", "license_check.py", "presets.json", "ui/index.html"):
        if not (here / needed).exists():
            print(f"Missing file: {needed}")
            return 1
    if not preflight():
        print("\nFix the packages above, then run the build again.")
        return 1

    system, sep, name = platform.system(), os.pathsep, "Norynth_File_Organizer"
    args = [sys.executable, "-m", "PyInstaller", "--noconsole", "--onedir" if onedir else "--onefile",
            f"--name={name}", "--clean", "--noconfirm",
            f"--add-data={here / 'ui'}{sep}ui", f"--add-data={here / 'presets.json'}{sep}.",
            "--collect-all=pymupdf", "--hidden-import=fitz", "--collect-all=docx", "--hidden-import=piexif",
            "--collect-all=webview",
            "--hidden-import=cryptography.hazmat.primitives.asymmetric.ed25519",
            "--hidden-import=license_check", "--hidden-import=engine"]
    if system == "Windows":   # pywebview talks to WebView2 through pythonnet
        for pkg in ("pythonnet", "clr_loader"):
            try:
                importlib.import_module(pkg)
                args.append(f"--collect-all={pkg}")
            except Exception:
                print(f"  note: {pkg} not importable (pywebview normally installs it on Windows)")
        args.append("--hidden-import=clr")
    args += [f"--exclude-module={m}" for m in EXCLUDES]

    icon = here / "assets" / ("icon.icns" if system == "Darwin" else "icon.ico")
    if icon.exists() and system != "Linux":
        args.append(f"--icon={icon}")
    vf = here / "version_info.txt"
    if system == "Windows" and vf.exists():
        args.append(f"--version-file={vf}")
    args.append(str(here / "app.py"))

    print("=" * 60, f"\nBuilding {name} ({'onedir' if onedir else 'onefile'}) on {system}\n" + "=" * 60)
    try:
        subprocess.run(args, cwd=here, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Build failed (exit code {e.returncode})")
        return e.returncode

    exe = name + (".exe" if system == "Windows" else "")
    out = here / "dist" / (name if onedir else exe)
    if out.exists():
        size = out.stat().st_size if out.is_file() else sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
        print(f"\nBuild successful: {out}  ({size / 1024 / 1024:.1f} MB)")
    warn = here / "build" / name / f"warn-{name}.txt"
    if warn.exists():
        text = warn.read_text(errors="ignore").lower()
        bad = [m for m in ("fitz", "pymupdf", "docx", "piexif", "webview", "clr") if f"missing module named {m}" in text]
        if bad:
            print(f"WARNING: PyInstaller reported missing modules: {bad}. See {warn}")
    print("Remember: put license.key next to the exe.")
    return 0


def clean() -> None:
    here = Path(__file__).parent.absolute()
    for d in ("build", "dist", "__pycache__"):
        if (here / d).exists():
            shutil.rmtree(here / d)
            print(f"Removed: {here / d}")
    for f in here.glob("*.spec"):
        f.unlink()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "clean":
        clean()
    else:
        sys.exit(build(onedir=(cmd == "onedir")))
