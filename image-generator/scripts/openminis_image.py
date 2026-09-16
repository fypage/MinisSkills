#!/usr/bin/env python3
"""OpenMinis model-use wrapper for user-configured image generation models.

No API key environment variable is required. Credentials stay inside OpenMinis provider settings.
The user adds/enables an image_output model; the assistant calls it via minis-model-use.
"""
import argparse
import base64
import json
import hashlib
import os
import subprocess
import sys
import time
import shutil
import tempfile
import re
import signal
import threading
from functools import wraps
from contextlib import contextmanager
from urllib.parse import quote, unquote, urlsplit
try:
    from PIL import Image
except Exception:
    Image = None
from pathlib import Path
from uuid import uuid4

WORKSPACE = Path("/var/minis/workspace")
ATTACHMENTS = Path("/var/minis/attachments")
PREFERRED_MODEL = "gpt-image-2"
# These providers return image data reliably only when prompted through an
# image-generation tool request. Their /images/generations response shape is
# not fully compatible with model-use's top-level prompt/size parser.
IMAGE_TOOL_PROVIDERS = {"picpi 皮皮工艺站"}


def die(msg, code=1):
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def parse_json_objects(text):
    """Decode every complete JSON object embedded in mixed CLI output."""
    decoder = json.JSONDecoder()
    objects = []
    pos = 0
    while pos < len(text):
        start = text.find("{", pos)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(text[start:])
            if isinstance(obj, dict):
                objects.append(obj)
            pos = start + end
        except json.JSONDecodeError:
            pos = start + 1
    return objects


def parse_json_from_output(text):
    objects = parse_json_objects(text)
    if not objects:
        raise ValueError("minis-model-use returned no JSON object")
    return objects[-1]


# Exact enums, not a character-pattern filter: arbitrary provider identifiers
# can contain prompts, credentials or URLs even when they look like safe tokens.
DIAGNOSTIC_CODES = frozenset({
    'invalid_api_key', 'authentication_error', 'permission_denied',
    'insufficient_quota', 'rate_limit_exceeded', 'rate_limit_error',
    'invalid_request_error', 'invalid_argument', 'model_not_found',
    'content_policy_violation', 'content_filter', 'safety_error',
    'server_error', 'internal_error', 'overloaded_error',
    'service_unavailable', 'timeout', 'connection_error',
})
DIAGNOSTIC_TYPES = DIAGNOSTIC_CODES | frozenset({
    'api_error', 'bad_request_error', 'not_found_error',
    'API_ERROR', 'INVALID_ARGUMENT', 'UNAUTHENTICATED',
    'PERMISSION_DENIED', 'RESOURCE_EXHAUSTED', 'NOT_FOUND',
    'INTERNAL', 'UNAVAILABLE', 'DEADLINE_EXCEEDED',
})
DIAGNOSTIC_STAGES = frozenset({
    'preparation', 'process_start', 'model_call', 'media_validation',
    'publication', 'unknown',
})


def safe_error_diagnostics(objects, stage):
    """Bounded envelope walk; never copy free text or infer HTTP from prose/code.

    JSON-encoded error/body/message envelopes are decoded only as whole JSON,
    never by extracting fragments from provider prose or request/prompt fields.
    Conflicting HTTP evidence is withheld rather than choosing a guessed status.
    """
    diagnostic = {'stage': stage if stage in DIAGNOSTIC_STAGES else 'unknown',
                  'http_status': None, 'error_code': 'unknown', 'error_type': 'unknown'}
    codes, types, statuses = set(), set(), set()
    found = False
    pending = [(objects, 0)]
    budget = 256
    envelopes = {'error', 'errors', 'response', 'data', 'result', 'cause',
                 'details', 'body', 'message'}
    while pending and budget:
        value, depth = pending.pop()
        budget -= 1
        if depth > 8:
            continue
        if isinstance(value, str):
            if len(value) > 65536:
                continue
            try:
                value = json.loads(value)
            except (ValueError, RecursionError):
                continue
        if isinstance(value, list):
            pending.extend((item, depth + 1) for item in value[:256])
        elif isinstance(value, dict):
            if value.get('error') or value.get('errors'):
                found = True
            for key in ('http_status', 'status_code', 'statusCode', 'status'):
                status = value.get(key)
                if isinstance(status, str) and re.fullmatch(r'[1-5][0-9]{2}', status):
                    status = int(status)
                if type(status) is int and 100 <= status <= 599:
                    statuses.add(status)
                    found = found or status >= 400
            for key, allowed, target in (
                    ('code', DIAGNOSTIC_CODES, codes),
                    ('type', DIAGNOSTIC_TYPES, types)):
                item = value.get(key)
                if isinstance(item, str) and item in allowed:
                    target.add(item)
            for key in envelopes:
                if key in value:
                    pending.append((value[key], depth + 1))
    if len(statuses) == 1:
        diagnostic['http_status'] = next(iter(statuses))
    if len(codes) == 1:
        diagnostic['error_code'] = next(iter(codes))
    if len(types) == 1:
        diagnostic['error_type'] = next(iter(types))
    return found, diagnostic


def select_model(model=None, provider=None):
    p = subprocess.run(
        ["minis-model-use", "list", "--modality", "image_output"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if p.returncode != 0:
        die("failed to list image_output models", 2)
    data = parse_json_from_output(p.stdout)
    models = data.get("models") or []
    if not models:
        die("No image_output model found. Add/enable one in OpenMinis Settings → Providers / Model Groups.")
    if provider:
        models = [m for m in models if m.get("instance_label") == provider]
        if not models:
            die(f"No image_output model found for provider: {provider}")
    if model:
        exact = [m for m in models if model in (
            m.get("model_id"), m.get("entry_id"), m.get("display_name"),
            f"{m.get('instance_label')}/{m.get('model_id')}")]
        if len(exact) > 1:
            die("Ambiguous model; specify --provider, qualified name or unique entry_id")
        if exact:
            m = exact[0]
            select_model.provider_type = m.get("provider_type", "OpenAI")
            return m.get("entry_id") or m.get("model_id"), m.get("instance_label")
        target = f"{provider}/{model}" if provider else model
        die(f"Requested image model is not currently available: {target}")
    preferred = [m for m in models if m.get("model_id") == PREFERRED_MODEL]
    m = preferred[0] if preferred else models[0]
    select_model.provider_type = m.get("provider_type", "OpenAI")
    return m.get("entry_id") or m.get("model_id"), m.get("instance_label")


def out_path(prefix):
    ATTACHMENTS.mkdir(parents=True, exist_ok=True)
    return ATTACHMENTS / f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}.png"


def require_pillow():
    if Image is None:
        die("Pillow is required before submitting images; install py3-pillow")


def minis_url(path):
    relative = Path(path).resolve().relative_to(ATTACHMENTS.resolve())
    return "minis://attachments/" + quote(relative.as_posix(), safe="/")


def validate_output_path(path):
    original = Path(path)
    p = original.resolve()
    root = ATTACHMENTS.resolve()
    if p == root or root not in p.parents:
        die("--output must be a file under /var/minis/attachments")
    if original.is_symlink() or p.exists():
        die("--output already exists; refusing to overwrite")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def prepare_reference_image(path, max_side=1024, jpeg_quality=85):
    require_pillow()
    p = Path(path)
    if not image_dimensions(p):
        die("reference image cannot be fully decoded")
    if max_side <= 0:
        return p
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    out = WORKSPACE / f"i2i_ref_{uuid4().hex}.png"
    try:
        with Image.open(p) as img:
            img.load()
            has_alpha = img.mode in ("RGBA", "LA") or "transparency" in img.info
            img.thumbnail((max_side, max_side))
            out = out if has_alpha else out.with_suffix(".jpg")
            with out.open("xb") as stream:
                os.chmod(out, 0o600)
                img.convert("RGBA" if has_alpha else "RGB").save(
                    stream, "PNG" if has_alpha else "JPEG", quality=jpeg_quality, optimize=True)
        return out
    except BaseException:
        out.unlink(missing_ok=True)
        raise


def detect_image_mime(path):
    """Detect supported image MIME strictly by magic bytes."""
    head = Path(path).read_bytes()[:16]
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    return None


def image_data_uri(path):
    p = Path(path)
    mime = detect_image_mime(p)
    if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
        die(f"unsupported reference image type: {p}")
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def image_dimensions(path):
    require_pillow()
    try:
        with Image.open(path) as img:
            for frame in range(getattr(img, "n_frames", 1)):
                img.seek(frame)
                img.load()
            return img.size
    except Exception:
        return None


def gcd(a, b):
    while b:
        a, b = b, a % b
    return a or 1


def aspect_from_dims(dims, fallback=None):
    """Exact reduced ratio; never silently substitute a nearby common ratio."""
    if dims:
        w, h = dims
        g = gcd(w, h)
        return f"{w // g}:{h // g}"
    return fallback or "auto"


def approximate_aspect(dims):
    w, h = dims
    common = [(1, 1), (4, 5), (3, 4), (2, 3), (3, 2), (4, 3),
              (16, 9), (9, 16), (21, 9), (3, 1)]
    cw, ch = min(common, key=lambda pair: abs(w / h - pair[0] / pair[1]))
    if abs(w / h - cw / ch) < 0.03:
        return f"约 {cw}:{ch}"
    return None


def infer_tier(quality, size, resolution=None):
    if resolution in ("1K", "2K", "4K"):
        return resolution
    q = (quality or "").lower()
    s = (size or "").lower().replace("*", "x")
    if q in ("high", "hd"):
        return "4K"
    if "x" in s:
        try:
            w, h = [int(x) for x in s.split("x", 1)]
            area = w * h
            if area > 5_000_000:
                return "4K"
            if area > 1_500_000:
                return "2K"
            return "1K"
        except Exception:
            pass
    if q == "medium":
        return "2K"
    if q in ("low", "auto", ""):
        return "1K"
    return "约1K"


def format_elapsed(seconds):
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m{seconds % 60:02d}s"


def _text(value):
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else (value or "")


def media_candidates(objects, stage):
    """Only accept task-scoped local files, never fetch URLs or reuse old media."""
    found = [stage / "result.png"]
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"path", "file_path", "local_path", "url", "minis_url"} and isinstance(item, str):
                    found.append(item)
                elif isinstance(item, (dict, list)):
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    found.append(item)
                else:
                    walk(item)
    walk(objects)
    seen = set()
    for item in found:
        text = str(item)
        if text.startswith("minis://attachments/"):
            p = ATTACHMENTS / unquote(text[len("minis://attachments/"):])
        elif urlsplit(text).scheme:
            continue
        else:
            p = Path(text)
            if not p.is_absolute():
                p = stage / p
        p = p.resolve()
        if stage.resolve() not in p.parents or p in seen or not p.is_file():
            continue
        seen.add(p)
        yield p


class TaskTerminated(BaseException):
    """Local termination is not evidence that the remote job was cancelled."""


def controlled_termination(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        if threading.current_thread() is not threading.main_thread():
            return func(*args, **kwargs)
        previous = signal.getsignal(signal.SIGTERM)
        def terminate(signum, frame):
            # A repeated TERM must not interrupt our cleanup.
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            raise TaskTerminated()
        # Nested generate/edit -> run must share the outer handler.
        owned = not getattr(previous, '_image_handler', False)
        terminate._image_handler = True
        if owned:
            signal.signal(signal.SIGTERM, terminate)
        try:
            return func(*args, **kwargs)
        finally:
            if owned:
                signal.signal(signal.SIGTERM, previous)
    return wrapped


def recovery_candidates(objects):
    """Only canonical attachment URLs, with no query/credentials/traversal."""
    found = set()
    def walk(value):
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str) and value.startswith('minis://attachments/'):
            try:
                parts = urlsplit(value)
                path = unquote(parts.path, errors='strict')
                segments = path[1:].split('/')
                if (parts.scheme != 'minis' or parts.netloc != 'attachments'
                        or parts.query or parts.fragment or '?' in value or '#' in value
                        or not segments or any(s in {'', '.', '..'} for s in segments)
                        or '\\' in path or '%' in path
                        or any(ord(c) < 32 or ord(c) == 127 for c in path)
                        or re.search(r'%(?![0-9a-fA-F]{2})', value)):
                    return
                found.add('minis://attachments/' + quote('/'.join(segments), safe='/'))
            except (ValueError, UnicodeError):
                return
    walk(objects)
    return [{'minis_url': url, 'verified': False,
             'note': 'Recovery candidate only; task ownership and image contents unverified'}
            for url in sorted(found)]


def save_journal(journal, record):
    with journal.open('w', encoding='utf-8') as stream:
        journal.chmod(0o600)
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def cleanup_action(record, operation, path, action):
    try:
        action()
        return True
    except Exception as exc:
        record.setdefault('cleanup_errors', []).append(
            {'operation': operation, 'path': str(path), 'error_type': type(exc).__name__})
        return False


def media_info(path, dims, mime):
    return {'path': str(path), 'minis_url': minis_url(path), 'verified': True,
            'pixel_size': f'{dims[0]}x{dims[1]}', 'aspect': aspect_from_dims(dims),
            'aspect_exact': aspect_from_dims(dims),
            'aspect_approximate': approximate_aspect(dims), 'mime': mime}


def inspect_stage(stage, record):
    """Bounded inspection, never follow directory or file symlinks."""
    images, hashes = [], set()
    pending, inspected = [stage], 0
    while pending and inspected < 256:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                inspected += 1
                if inspected > 256:
                    break
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False) or entry.stat().st_size > 100 * 1024 * 1024:
                    continue
                candidate = Path(entry.path)
                dims = image_dimensions(candidate)
                mime = detect_image_mime(candidate) if dims else None
                if dims and mime:
                    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
                    if digest not in hashes:
                        hashes.add(digest)
                        images.append((candidate, dims, mime))
    images.sort(key=lambda item: (item[0] != stage / 'result.png', str(item[0])))
    record['verified_media'] = [media_info(*item) for item in images]
    record['inspection_limit_reached'] = inspected >= 256
    return images


def atomic_publish(candidate, target, dims, record, journal):
    """Same-filesystem hard-link commit is atomic and never replaces a name."""
    fd, name = tempfile.mkstemp(prefix='.image_publish_', dir=target.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as dst, candidate.open('rb') as src:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        if image_dimensions(temp) != dims or temp.read_bytes() != candidate.read_bytes():
            raise ValueError('Publication verification failed')
        temp.chmod(0o644)
        # Block TERM across commit + per-image journal so the link is accounted for.
        with block_termination():
            os.link(temp, target)
            info = media_info(target, dims, detect_image_mime(target))
            record['images'].append(info)
            save_journal(journal, record)
        return info
    finally:
        cleanup_action(record, 'remove_publication_temp', temp,
                       lambda: temp.unlink(missing_ok=True))


@contextmanager
def block_termination():
    old = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, old)


@controlled_termination
def run_model_use(payload, output, provider, model, timeout=900, prompt_text=""):
    require_pillow()
    output = validate_output_path(output)
    if timeout <= 0:
        die("--timeout must be positive")
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    job_id = uuid4().hex
    req = WORKSPACE / f"image_model_use_{job_id}.json"
    journal = WORKSPACE / f"image_job_{job_id}.json"
    stage = Path(tempfile.mkdtemp(prefix=f".image_job_{job_id}_", dir=ATTACHMENTS))
    # Native-offload runs under a different UID: short-lived readable request
    # and writable task directory are required on some Android versions.
    stage.chmod(0o777)
    started = time.time()
    requested_n = payload.get("n", payload.get("generation_config", {}).get("number_of_images", 1))
    record = {"status": "preparing", "model": model, "provider": provider,
              "prompt_sha256": hashlib.sha256(prompt_text.encode()).hexdigest(),
              "requested_n": requested_n, "request_file_removed": False,
              "raw_response_preserved": False}
    record.update(job_id=job_id, stage_path=str(stage), images=[], verified_media=[],
                  recovery_candidates=[], cleanup_errors=[], remote_cancelled=False)
    result = None
    objects = []
    diagnostic_stage = 'preparation'
    try:
        with req.open("x", encoding="utf-8") as stream:
            req.chmod(0o644)
            json.dump(payload, stream, ensure_ascii=False)
        cmd = ["minis-model-use", "run", "--model", model]
        if provider:
            cmd += ["--provider", provider]
        cmd += ["--input", str(req), "--output", str(stage / "result.png")]
        record["status"] = "submitted"
        save_journal(journal, record)
        diagnostic_stage = 'model_call'
        try:
            p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            # Normalize streams separately: TimeoutExpired may contain mixed bytes/str.
            raw = _text(exc.stdout) + _text(exc.stderr)
            objects = parse_json_objects(raw)
            record.update(status="ambiguous", reason="timeout", timeout_seconds=timeout)
            die(f"Image outcome ambiguous; no automatic retry. Journal: {journal}", 3)
        except OSError:
            diagnostic_stage = 'process_start'
            record.update(status="failed_pre_submit", reason="process_start_failed")
            die(f"Unable to start model CLI. Journal: {journal}", 2)
        raw = _text(p.stdout)
        objects = parse_json_objects(raw)
        record["returncode"] = p.returncode
        has_error, _ = safe_error_diagnostics(objects, diagnostic_stage)
        if p.returncode or has_error:
            # Unknown CLI/provider failures may follow successful submission.
            record.update(status="ambiguous", reason="cli_or_provider_error")
            die(f"Image outcome ambiguous; no automatic retry. Journal: {journal}", 3)
        warnings = []
        if not objects:
            warnings.append("CLI returned no JSON metadata; only task-local files were inspected")
        if any(obj.get("warnings") for obj in objects):
            warnings.append("CLI reported parameter warnings; raw content withheld for privacy")
        diagnostic_stage = 'media_validation'
        images = inspect_stage(stage, record)
        record['recovery_candidates'] = recovery_candidates(objects)
        if not images:
            record.update(status="ambiguous", reason="no_valid_fresh_media")
            die(f"No valid fresh media; outcome ambiguous. Journal: {journal}", 3)
        diagnostic_stage = 'publication'
        delivered = []
        for index, (candidate, dims, mime) in enumerate(images):
            target = output if index == 0 else output.with_name(
                f"{output.stem}_{job_id}_{index + 1}{output.suffix}")
            target = validate_output_path(target)
            delivered.append(atomic_publish(candidate, target, dims, record, journal))
        if len(delivered) != requested_n:
            warnings.append(f"Requested {requested_n}, validated {len(delivered)}; no replacement request sent")
        record.update(status="succeeded", actual_n=len(delivered), warnings=warnings)
        result = {**record, **delivered[0], "images": delivered,
                  "journal": str(journal), "n": requested_n,
                  "quality": payload.get("quality"), "size": payload.get("size"),
                  "elapsed": format_elapsed(time.time() - started)}
    except BaseException:
        _, record['diagnostics'] = safe_error_diagnostics(objects, diagnostic_stage)
        if record["status"] == "submitted":
            record.update(status="ambiguous", reason="interrupted_or_post_submit_failure")
        elif record["status"] == "preparing":
            record.update(status="failed_pre_submit", reason="preparation_failure")
        raise
    finally:
        # Request secrets are removed independently from generated media.
        with block_termination():
            record['request_file_removed'] = cleanup_action(
                record, 'remove_request', req, lambda: req.unlink(missing_ok=True))
            record['recovery_candidates'] = recovery_candidates(objects)
            if record['status'] != 'succeeded':
                cleanup_action(record, 'inspect_retained_media', stage,
                               lambda: inspect_stage(stage, record))
            # Never delete a submitted task directory on an uncertain outcome:
            # native offload may still be writing after the local CLI stops.
            if record['status'] in {'succeeded', 'failed_pre_submit'}:
                removed = cleanup_action(record, 'remove_stage', stage,
                                         lambda: shutil.rmtree(stage))
                record['stage_retained'] = not removed
                if removed and record['status'] == 'succeeded':
                    record['verified_media'] = list(record['images'])
            else:
                record['stage_retained'] = True
            record['actual_n'] = len(record['images'])
            record['cleanup_status'] = 'failed' if record['cleanup_errors'] else 'complete'
            save_journal(journal, record)
            if record['status'] == 'ambiguous':
                print(json.dumps({'status': 'ambiguous', 'journal': str(journal),
                    'diagnostics': record.get('diagnostics', {}),
                    'stage_path': str(stage), 'verified_media': record['verified_media'],
                    'images': record['images'], 'recovery_candidates': record['recovery_candidates'],
                    'remote_cancelled': False, 'cleanup_status': record['cleanup_status']},
                    ensure_ascii=False), file=sys.stderr)
    if result is not None:
        result.update(record)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result


def build_common(args, selected_model):
    if not 1 <= args.n <= 5:
        die("--n must be 1..5")
    gemini = getattr(select_model, "provider_type", "OpenAI").lower() in {"gemini", "google", "googleai"}
    extra = {}
    if args.extra_body:
        try:
            extra = json.loads(args.extra_body)
        except (ValueError, TypeError):
            die("--extra-body must be a JSON object")
        if not isinstance(extra, dict):
            die("--extra-body must be a JSON object")
        protected = {"model", "prompt", "messages", "images", "n", "size", "quality",
                     "resolution", "response_format", "generation_config", "number_of_images",
                     "image_size", "aspect_ratio", "passthrough", "endpoint", "endpoint_path",
                     "image_endpoint", "extra_headers", "extra_body", "tools", "tool_choice"}
        if protected.intersection(extra):
            die("--extra-body cannot override core fields or routing")
    if gemini:
        if extra or args.quality != "auto" or args.response_format != "url":
            die("Gemini does not support --extra-body, --quality or --response-format overrides")
        if args.n > 4:
            die("Gemini number_of_images must be 1..4")
        config = {"number_of_images": args.n}
        size = args.size
        if size and size != "auto":
            if "x" in size:
                try:
                    dims = tuple(int(x) for x in size.split("x"))
                    if len(dims) != 2 or min(dims) <= 0:
                        raise ValueError()
                    size = aspect_from_dims(dims)
                except ValueError:
                    die("Invalid pixel size")
                print("Warning: Gemini pixel size converted to aspect ratio, not exact pixels", file=sys.stderr)
            if size not in {"1:1", "16:9", "9:16", "4:3", "3:4"}:
                die("Unsupported Gemini aspect ratio")
            config["aspect_ratio"] = size
        if args.resolution:
            config["image_size"] = args.resolution
        return {"generation_config": config}
    if not isinstance(args.size, str) or not re.fullmatch(r'(?:auto|[1-9][0-9]*x[1-9][0-9]*)', args.size):
        die('OpenAI --size must be auto or positive integer WxH')
    if args.quality not in {'auto', 'low', 'medium', 'high', 'standard', 'hd'}:
        die('Unknown OpenAI quality; allowed: auto, low, medium, high, standard, hd')
    payload = {"size": args.size, "quality": args.quality, "n": args.n,
               "response_format": args.response_format}
    if args.resolution:
        print("Warning: resolution is provider-specific and may be ignored", file=sys.stderr)
        extra["resolution"] = args.resolution
    if extra:
        payload["extra_body"] = extra
    return payload


def special_payload(args):
    if args.quality != "auto" or args.resolution or args.extra_body or args.response_format != "url":
        die("Special tool route cannot honor quality/resolution/response-format/extra-body overrides")
    if args.n != 1:
        die("Special tool route cannot guarantee multi-image count; --n must be 1")
    print("Warning: special tool route size is only a prompt hint; response-format is not controlled", file=sys.stderr)
    text = args.prompt
    if args.size and args.size != "auto":
        text += f"\nRequested output aspect ratio or size: {args.size}."
    return {"messages": [{"role": "user", "content": text}],
            "tools": [{"type": "image_generation"}], "tool_choice": "required"}


@controlled_termination
def generate(args):
    require_pillow()
    model, provider = select_model(args.model, args.provider)
    if provider in IMAGE_TOOL_PROVIDERS:
        payload = special_payload(args)
    else:
        payload = build_common(args, model)
        if "generation_config" in payload:
            payload["messages"] = [{"role": "user", "content": args.prompt}]
        else:
            payload["prompt"] = args.prompt
    output = validate_output_path(args.output) if args.output else out_path("image_gen")
    run_model_use(payload, output, provider, model, args.timeout, args.prompt)


@controlled_termination
def edit(args):
    require_pillow()
    model, provider = select_model(args.model, args.provider)
    if not 1 <= len(args.image) <= 16:
        die("1..16 reference images are required")
    output = validate_output_path(args.output) if args.output else out_path("image_edit")
    payload = special_payload(args) if provider in IMAGE_TOOL_PROVIDERS else build_common(args, model)
    prepared = []
    try:
        for img in args.image:
            p = Path(img)
            if not p.is_file() or p.stat().st_size > 50 * 1024 * 1024:
                die("Reference must be a local file no larger than 50 MiB")
            prepared.append(prepare_reference_image(p, args.ref_max_side, args.ref_quality))
        data_uris = [image_data_uri(img) for img in prepared]
        if "generation_config" in payload:
            payload["messages"] = [{"role": "user", "content": [
                {"type": "text", "text": args.prompt},
                *[{"type": "image_url", "image_url": {"url": uri}} for uri in data_uris]]}]
        else:
            payload["images"] = data_uris
            if provider not in IMAGE_TOOL_PROVIDERS:
                payload["prompt"] = args.prompt
        run_model_use(payload, output, provider, model, args.timeout, args.prompt)
    finally:
        originals = {Path(img).resolve() for img in args.image}
        for ref in prepared:
            if ref.resolve() not in originals:
                cleanup = {'cleanup_errors': []}
                if not cleanup_action(cleanup, 'remove_reference', ref,
                                      lambda: ref.unlink(missing_ok=True)):
                    print(json.dumps({'cleanup_status': 'failed', **cleanup}), file=sys.stderr)


def list_models_cli():
    p = subprocess.run(["minis-model-use", "list", "--modality", "image_output"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(p.stdout, end="")
    raise SystemExit(p.returncode)


def main():
    p = argparse.ArgumentParser(description="Generate/edit images via the user's OpenMinis image_output model")
    p.add_argument("--list-models", action="store_true", help="List configured image_output models and exit")
    sub = p.add_subparsers(dest="cmd")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--model", default="", help="Optional model id; omitted = auto-select image_output model")
    common.add_argument("--provider", default="", help="Optional provider label; omitted = auto-select")
    common.add_argument("--size", default="1200x675")
    common.add_argument("--quality", default="auto")
    common.add_argument("--resolution", default="", choices=["", "1K", "2K", "4K"], help="Optional provider-specific resolution tier; omitted by default")
    common.add_argument("--n", type=int, default=1, choices=range(1, 6), metavar="1..5")
    common.add_argument("--response-format", default="url", choices=["b64_json", "url"], help="Default url reduces large base64 timeout risk")
    common.add_argument("--output")
    common.add_argument("--timeout", type=int, default=900, help="Request timeout seconds; timeout is treated as ambiguous and never auto-retried")
    common.add_argument("--extra-body", help="JSON object merged into model-use request body")
    g = sub.add_parser("generate", parents=[common])
    g.add_argument("--prompt", required=True)
    g.set_defaults(func=generate)
    e = sub.add_parser("edit", parents=[common])
    e.add_argument("--prompt", required=True)
    e.add_argument("--image", action="append", required=True)
    e.add_argument("--ref-max-side", type=int, default=1024, help="Reference longest side; 0 keeps original (larger payload)")
    e.add_argument("--ref-quality", type=int, default=85, choices=range(40, 96), metavar="40..95", help="JPEG quality; alpha images stay PNG")
    e.set_defaults(func=edit)
    args = p.parse_args()
    if args.list_models:
        list_models_cli()
    if not getattr(args, "cmd", None):
        p.error("a command is required unless --list-models is used")
    args.func(args)


if __name__ == "__main__":
    main()
