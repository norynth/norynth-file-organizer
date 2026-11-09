import base64
import sys
from pathlib import Path

PUBLIC_KEY_B64 = "Q5YPhu/j8hPOAOdgV+sT4E6EixttvGjXWU+4q2No7hU="
PRODUCT_ID = "norynth-file-organizer-v1"
LICENSE_FILENAME = "license.key"


def _verify_signature(order_id: str, sig_b64: str) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        return False
    try:
        public_bytes = base64.b64decode(PUBLIC_KEY_B64)
        public_key = Ed25519PublicKey.from_public_bytes(public_bytes)
        pad = "=" * (-len(sig_b64) % 4)
        sig_bytes = base64.urlsafe_b64decode(sig_b64 + pad)
        payload = f"{PRODUCT_ID}:{order_id}".encode()
        public_key.verify(sig_bytes, payload)
        return True
    except Exception:
        return False


def find_license_file():
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / LICENSE_FILENAME)
        if hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / LICENSE_FILENAME)
    candidates.append(Path(__file__).resolve().parent / LICENSE_FILENAME)
    candidates.append(Path.cwd() / LICENSE_FILENAME)
    for c in candidates:
        if c.exists():
            return c
    return None


def validate_license():
    path = find_license_file()
    if not path:
        return False, "license.key not found"
    try:
        with open(path, "r", encoding="utf-8") as f:
            key = f.readline().strip()
    except Exception as e:
        return False, f"could not read license.key: {e}"
    if not key.startswith("NORYNTH-"):
        return False, "invalid key format"
    _, rest = key.split("-", 1)
    parts = rest.split("|", 1)
    if len(parts) != 2:
        return False, "invalid key structure"
    order_id, sig_b64 = parts
    if _verify_signature(order_id, sig_b64):
        return True, order_id
    return False, "signature verification failed"


def require_license_or_exit():
    valid, msg = validate_license()
    if valid:
        return

    html = f"""<!doctype html><html><head><meta charset="utf-8">
    <title>Norynth — License Required</title>
    <style>
      body {{ font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
              padding: 2.5em; color: #111; background: #fff; }}
      h2   {{ margin: 0 0 .6em; font-size: 20px; }}
      code {{ background: #f2f2f2; padding: 2px 6px; border-radius: 4px; }}
      .hint {{ color: #555; font-size: 14px; margin-top: 1.4em; }}
    </style></head><body>
    <h2>Norynth File Organizer — License Required</h2>
    <p>No valid license was found.</p>
    <p><b>Reason:</b> {msg}</p>
    <p>Make sure <code>license.key</code> is in the same folder as the application.</p>
    <p class="hint">Support: support@norynth.com</p>
    </body></html>"""

    try:
        import webview
        webview.create_window("Norynth — License Required", html=html,
                              width=580, height=380, resizable=False)
        webview.start()
        sys.exit(1)
    except Exception:
        pass  # fall through to log file

    try:
        log_path = Path(sys.executable).parent / "norynth_license_error.txt"
    except Exception:
        log_path = Path.cwd() / "norynth_license_error.txt"
    try:
        log_path.write_text(
            "Norynth File Organizer — License Required\n"
            f"Reason: {msg}\n"
            "Place license.key in the same folder as the application.\n"
            "Support: support@norynth.com\n",
            encoding="utf-8",
        )
    except Exception:
        pass

    sys.exit(1)
