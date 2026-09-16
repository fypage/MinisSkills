#!/usr/bin/env python3
"""Recover an existing ``minis://attachments/`` image through browser canvas.

Canvas extraction re-encodes the rendered image as PNG.  It is therefore a
pixel-level compatibility recovery, not restoration of the original bytes;
metadata, animation and the original colour encoding may be lost.
"""
import argparse
import base64
import binascii
import io
import json
import os
import re
import secrets
import signal
import threading
from contextlib import contextmanager
import stat
import subprocess
import time
from pathlib import Path
from urllib.parse import quote, unquote_to_bytes, urlsplit

ATTACHMENTS = Path("/var/minis/attachments")
OFFLOADS = Path("/var/minis/offloads")
MAX_CLI_TEXT = 96 * 1024 * 1024
MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_OFFLOAD_BYTES = 96 * 1024 * 1024
MAX_PIXELS = 64_000_000
_DATA_RE = re.compile(
    r"data:image/(?P<type>png|jpeg|webp);base64,(?P<data>[^\"'<>]+)",
    re.IGNORECASE,
)


def run(args, timeout=120):
    return subprocess.run(args, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=timeout)


def json_objects(text):
    """Return JSON objects found in ordinary or noisy CLI output."""
    if not isinstance(text, str):
        return []
    dec, out, pos = json.JSONDecoder(), [], 0
    while pos < len(text):
        start = text.find("{", pos)
        if start < 0:
            break
        try:
            obj, used = dec.raw_decode(text[start:])
            if isinstance(obj, dict):
                out.append(obj)
            pos = start + used
        except json.JSONDecodeError:
            pos = start + 1
    return out


def _text_values(value, depth=0):
    if depth > 8:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result = []
        # Real minis CLI envelopes commonly use data.text, text, output or result.
        for key in ("text", "output", "result", "content", "data"):
            if key in value:
                result.extend(_text_values(value[key], depth + 1))
        return result
    if isinstance(value, list):
        result = []
        for item in value[:100]:
            result.extend(_text_values(item, depth + 1))
        return result
    return []


def envelope_text(raw):
    objs = json_objects(raw)
    for obj in reversed(objs):
        values = _text_values(obj)
        if values:
            return values[0]
    return raw.strip() if isinstance(raw, str) else ""


def _strict_unquote(value):
    if re.search(r"%(?![0-9A-Fa-f]{2})", value):
        raise ValueError("malformed percent escape")
    try:
        return unquote_to_bytes(value).decode("utf-8", "strict")
    except UnicodeError as exc:
        raise ValueError("URL path is not valid UTF-8") from exc


def validate_media_url(url):
    """Validate and canonically encode an attachments resource URL."""
    if not isinstance(url, str) or any(ord(c) < 0x20 for c in url):
        raise ValueError("invalid media URL")
    parts = urlsplit(url)
    if (parts.scheme != "minis" or parts.netloc != "attachments" or
            parts.query or parts.fragment or parts.username or parts.password):
        raise ValueError("URL must be a minis://attachments/ resource URL")
    if not parts.path.startswith("/") or parts.path == "/":
        raise ValueError("attachment URL must name a file")
    decoded = _strict_unquote(parts.path)
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in decoded):
        raise ValueError("control characters are forbidden in attachment paths")
    # Encoded separators are ambiguous and must not alter path segmentation.
    if "%2f" in parts.path.lower() or "%5c" in parts.path.lower():
        raise ValueError("encoded path separators are forbidden")
    segments = decoded.split("/")[1:]
    if any(s in ("", ".", "..") for s in segments) or "\\" in decoded:
        raise ValueError("unsafe attachment path")
    canonical = quote(decoded, safe="/-._~")
    return "minis://attachments" + canonical


def validate_output_path(output):
    target = Path(output)
    if not target.is_absolute():
        raise ValueError("output must be an absolute attachments path")
    root = ATTACHMENTS.resolve(strict=True)
    # resolve(strict=False) also resolves an existing symlink in any component.
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("output must remain under /var/minis/attachments") from exc
    if resolved == root:
        raise ValueError("output must name a file, not the attachments directory")
    if target.exists() or target.is_symlink():
        raise FileExistsError("output already exists; refusing to overwrite")
    parent = target.parent.resolve(strict=True)
    try:
        parent.relative_to(root)
    except ValueError as exc:
        raise ValueError("output parent escapes attachments") from exc
    if not parent.is_dir():
        raise ValueError("output parent is not a directory")
    return target


def _safe_offload(path_text):
    try:
        decoded = _strict_unquote(path_text)
    except ValueError:
        return None
    candidate = (OFFLOADS / decoded.lstrip("/")) if not decoded.startswith("/") else Path(decoded)
    root = OFFLOADS.resolve(strict=True)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    try:
        info = resolved.stat()
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_OFFLOAD_BYTES:
        return None
    return resolved


def offload_candidates(raw):
    found = []
    patterns = (r"minis://offloads/([^\s\"'<>]+)",
                r"(/var/minis/offloads/[^\s\"'<>]+)")
    for pattern in patterns:
        for hit in re.findall(pattern, raw or ""):
            path = _safe_offload(hit)
            if path is not None and path not in found:
                found.append(path)
    return found


def _candidate_texts(raw):
    if not isinstance(raw, str) or len(raw) > MAX_CLI_TEXT:
        return []
    texts = [raw]
    for obj in json_objects(raw):
        texts.extend(_text_values(obj))
    for path in offload_candidates(raw):
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if len(content) <= MAX_CLI_TEXT:
            texts.append(content)
            for obj in json_objects(content):
                texts.extend(_text_values(obj))
    return texts


def data_url_from_output(raw):
    """Extract and strictly decode a supported image data URL.

    Returns ``(bytes, media_type)`` or ``None``. The decoded bytes are only a
    candidate; callers must still perform complete image validation.
    """
    for text in _candidate_texts(raw):
        # Strip only the CLI's terminal metadata line, after JSON unescaping.
        # Never trim arbitrary non-base64 suffixes into a seemingly valid image.
        text = re.sub(r"\r?\n[ \t]*tab_id:[ \t]*[0-9]+[ \t]*(?:\r?\n)?\Z", "", text)
        for match in _DATA_RE.finditer(text):
            payload = re.sub(r"\s+", "", match.group("data"))
            if len(payload) > ((MAX_IMAGE_BYTES + 2) // 3) * 4 + 4:
                continue
            try:
                raw_bytes = base64.b64decode(payload, validate=True)
            except (binascii.Error, ValueError):
                continue
            if len(raw_bytes) <= MAX_IMAGE_BYTES:
                return raw_bytes, match.group("type").lower()
    return None


def tab_id_from_output(raw):
    """Parse a dedicated tab ID from JSON envelopes or human CLI text."""
    for obj in reversed(json_objects(raw)):
        stack = [obj]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                for key, item in value.items():
                    if key.lower() in ("tab_id", "tabid") and isinstance(item, (str, int)):
                        text = str(item)
                        if text.isdigit():
                            return text
                    if isinstance(item, (dict, list)):
                        stack.append(item)
            elif isinstance(value, list):
                stack.extend(value[:100])
    match = re.search(r"\btab(?:_id|\s+id|\s+)(?::|=)?\s*(\d+)\b", raw or "", re.I)
    return match.group(1) if match else None


def validate_image(raw_bytes, declared_type):
    """Fully decode an image and require actual PNG canvas output."""
    if declared_type != "png" or not raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("canvas result is not a PNG")
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        raise RuntimeError("Pillow is required for complete image validation") from exc
    old_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(raw_bytes)) as image:
            if image.format != "PNG" or image.width < 1 or image.height < 1:
                raise ValueError("invalid PNG dimensions or format")
            if image.width * image.height > MAX_PIXELS:
                raise ValueError("image exceeds pixel limit")
            image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("PNG failed complete Pillow decoding") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = old_limit


@contextmanager
def termination_cleanup():
    """Unwind on SIGTERM in CLI/main-thread calls; restore caller handlers.

    SIGKILL, process death, and a tab created without a returned ID cannot be
    cleaned up reliably. Worker-thread callers must arrange signal handling.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.getsignal(signal.SIGTERM)

    def terminate(signum, frame):
        # A repeated TERM must not interrupt the cleanup already in progress.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def publish_exclusive(target, raw_bytes):
    """Publish through a unique temp file and atomically refuse overwrite."""
    tmp = target.parent / (".browser-recover-" + secrets.token_hex(16) + ".tmp")
    with termination_cleanup():
        fd = None
        owned = False
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            owned = True
            with os.fdopen(fd, "wb") as handle:
                fd = None  # handle now owns the descriptor
                handle.write(raw_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            # Atomic, no-clobber commit: never remove the published target,
            # even if an interrupt arrives immediately after this link.
            os.link(tmp, target, follow_symlinks=False)
        finally:
            if fd is not None:
                os.close(fd)
            if owned:
                tmp.unlink(missing_ok=True)


def recover(minis_url, output, attempts=15):
    with termination_cleanup():
        return _recover(minis_url, output, attempts)


def _recover(minis_url, output, attempts=15):
    try:
        safe_url = validate_media_url(minis_url)
        target = validate_output_path(output)
    except (ValueError, OSError) as exc:
        return False, str(exc)
    try:
        opened = run(["minis-browser-use", "new_tab", "--url", safe_url], 30)
    except Exception as exc:
        return False, "browser could not open media URL: " + str(exc)
    tab = tab_id_from_output(opened.stdout)
    if tab is None:
        return False, "browser did not return a dedicated tab ID; refusing default-tab access"

    script = ("var i=document.querySelector('img');"
              "if(!i||!i.complete||!i.naturalWidth)return 'NOT_READY';"
              "var c=document.createElement('canvas');"
              "c.width=i.naturalWidth;c.height=i.naturalHeight;"
              "c.getContext('2d').drawImage(i,0,0);"
              "return c.toDataURL('image/png');")
    outcome = (False, "canvas extraction returned no valid image")
    try:
        if opened.returncode:
            raise RuntimeError("browser could not open media URL")
        count = max(0, min(int(attempts), 100))
        for index in range(count):
            result = run(["minis-browser-use", "execute_js", "--tab-id", tab,
                          "--script", script], 120)
            if result.returncode == 0:
                candidate = data_url_from_output(result.stdout)
                if candidate:
                    try:
                        validate_image(*candidate)
                        # Re-check immediately before atomic no-clobber publish.
                        validate_output_path(str(target))
                        publish_exclusive(target, candidate[0])
                        outcome = (True, f"recovered {len(candidate[0])} bytes; canvas re-encoded PNG, not original bytes")
                        break
                    except (ValueError, RuntimeError, OSError, FileExistsError):
                        pass
            if index + 1 < count:
                time.sleep(0.5)
    except Exception as exc:
        outcome = (False, "browser extraction failed: " + str(exc))
    finally:
        try:
            closed = run(["minis-browser-use", "close_tab", "--tab-id", tab], 15)
            if closed.returncode:
                outcome = (outcome[0], outcome[1] + "; dedicated tab close failed")
        except (Exception, KeyboardInterrupt, SystemExit):
            # Preserve both a committed success and any active interruption.
            outcome = (outcome[0], outcome[1] + "; dedicated tab close raised an error")
    return outcome


def main():
    parser = argparse.ArgumentParser(description="Recover an existing minis:// image without regenerating")
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--attempts", type=int, default=15)
    args = parser.parse_args()
    ok, message = recover(args.url, args.output, args.attempts)
    print(json.dumps({"status": "ok" if ok else "error", "recovered": ok,
                      "url": args.url, "path": args.output, "message": message},
                     ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
