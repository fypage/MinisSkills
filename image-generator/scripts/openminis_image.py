#!/usr/bin/env python3
"""OpenMinis model-use wrapper for user-configured image generation models.

No API key environment variable is required. Credentials stay inside OpenMinis provider settings.
The user adds/enables an image_output model; the assistant calls it via minis-model-use.
"""
import argparse
import base64
import json
import mimetypes
import hashlib
import os
import subprocess
import sys
import time
try:
    from PIL import Image
except Exception:
    Image = None
from pathlib import Path
from uuid import uuid4

WORKSPACE = Path("/var/minis/workspace")
ATTACHMENTS = Path("/var/minis/attachments")
PREFERRED_MODEL = "gpt-image-2"
PREFERRED_PROVIDERS = ["智画创"]
# Providers confirmed retired/unavailable. Keep this set for future outages so
# auto-selection can block them without removing the user's configuration.
DEPRECATED_PROVIDERS = set()
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
        die("minis-model-use did not return JSON:\n" + text[:1000])
    return objects[-1]


def select_model(model=None, provider=None, allow_deprecated=False):
    if provider in DEPRECATED_PROVIDERS and not allow_deprecated:
        die(f"Provider is retired/unavailable and blocked for new jobs: {provider}")
    if model and provider:
        return model, provider
    p = subprocess.run(
        ["minis-model-use", "list", "--modality", "image_output"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if p.returncode != 0:
        die("failed to list image_output models:\n" + p.stdout, p.returncode)
    data = parse_json_from_output(p.stdout)
    models = data.get("models") or []
    if not models:
        die("No image_output model found. Add/enable one in OpenMinis Settings → Providers / Model Groups.")
    if provider:
        models = [m for m in models if m.get("instance_label") == provider]
        if not models:
            die(f"No image_output model found for provider: {provider}")
    if not allow_deprecated:
        active = [m for m in models if m.get("instance_label") not in DEPRECATED_PROVIDERS]
        if active:
            models = active
        elif not provider:
            die("Only deprecated/unavailable image providers are configured. Add or enable a replacement provider before generating a new image.")
    if model:
        exact = [m for m in models if m.get("model_id") == model or m.get("entry_id") == model]
        if exact:
            m = exact[0]
            return m.get("model_id") or m.get("entry_id"), m.get("instance_label")
        return model, provider
    preferred = [
        m for provider_name in PREFERRED_PROVIDERS
        for m in models
        if m.get("instance_label") == provider_name and m.get("model_id") == PREFERRED_MODEL
    ]
    if not preferred:
        preferred = [m for m in models if m.get("model_id") == PREFERRED_MODEL]
    m = preferred[0] if preferred else models[0]
    return m.get("model_id") or m.get("entry_id"), m.get("instance_label")


def out_path(prefix):
    ATTACHMENTS.mkdir(parents=True, exist_ok=True)
    return ATTACHMENTS / f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}.png"


def minis_url(path):
    return "minis://attachments/" + path.name


def validate_output_path(path):
    p = Path(path).resolve()
    root = ATTACHMENTS.resolve()
    if p != root and root not in p.parents:
        die("--output must be under /var/minis/attachments")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def prepare_reference_image(path, max_side=1024, jpeg_quality=85):
    p = Path(path)
    if Image is None or max_side <= 0:
        return p
    try:
        img = Image.open(p)
        # Preserve transparency and hard edges for logos/product assets.
        has_alpha = img.mode in ("RGBA", "LA") or "transparency" in img.info
        img.thumbnail((max_side, max_side))
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        if has_alpha:
            out = WORKSPACE / f"i2i_ref_{uuid4().hex[:8]}.png"
            img.convert("RGBA").save(out, "PNG", optimize=True)
        else:
            out = WORKSPACE / f"i2i_ref_{uuid4().hex[:8]}.jpg"
            img.convert("RGB").save(out, "JPEG", quality=jpeg_quality, optimize=True)
        return out
    except Exception:
        return p


def detect_image_mime(path):
    """Detect supported image MIME by magic bytes, not filename alone."""
    head = Path(path).read_bytes()[:16]
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    return mimetypes.guess_type(str(path))[0]


def image_data_uri(path):
    p = Path(path)
    mime = detect_image_mime(p)
    if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
        die(f"unsupported reference image type: {p}")
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def image_dimensions(path):
    if Image is None:
        return None
    try:
        img = Image.open(path)
        return img.size
    except Exception:
        return None


def gcd(a, b):
    while b:
        a, b = b, a % b
    return a or 1


def aspect_from_dims(dims, fallback=None):
    if dims:
        w, h = dims
        g = gcd(w, h)
        rw, rh = w // g, h // g
        common = [(1,1),(4,5),(3,4),(2,3),(3,2),(4,3),(16,9),(9,16),(21,9),(3,1)]
        for cw, ch in common:
            if abs((w / h) - (cw / ch)) < 0.03:
                return f"{cw}:{ch}"
        return f"{rw}:{rh}"
    return fallback or "auto"


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


def run_model_use(payload, output, provider, model, timeout=900, prompt_text=""):
    started = time.time()
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    req = WORKSPACE / f"image_model_use_{uuid4().hex[:8]}.json"
    req.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # minis-model-use may execute through Android native-offload under a
    # different UID. Keep non-secret request JSON world-readable so that the
    # native process can open it; provider credentials are never stored here.
    req.chmod(0o644)
    cmd = ["minis-model-use", "run", "--model", model]
    if provider:
        cmd += ["--provider", provider]
    cmd += ["--input", str(req), "--output", str(output)]
    prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest() if prompt_text else None
    journal = WORKSPACE / f"image_job_{uuid4().hex[:8]}.json"
    journal_data = {"status": "submitted", "request": str(req), "output": str(output), "provider": provider, "model": model, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "prompt_sha256": prompt_hash, "prompt_preserved": True}
    journal.write_text(json.dumps(journal_data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raw = (e.stdout or "") + (e.stderr or "")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        error_dump = WORKSPACE / ".image_gen_last_error.json"
        error_dump.write_text(json.dumps({**journal_data, "status": "ambiguous_timeout", "timeout_seconds": timeout, "raw_output": raw}, ensure_ascii=False, indent=2), encoding="utf-8")
        journal_data.update({"status": "ambiguous_timeout", "timeout_seconds": timeout, "error_dump": str(error_dump)})
        journal.write_text(json.dumps(journal_data, ensure_ascii=False, indent=2), encoding="utf-8")
        die(f"image request timed out after {timeout}s; outcome is ambiguous, so it was not retried. Journal: {journal}", 3)
    print(p.stdout, end="")
    if p.returncode != 0:
        error_dump = WORKSPACE / ".image_gen_last_error.json"
        error_dump.write_text(json.dumps({**journal_data, "status": "failed", "returncode": p.returncode, "raw_output": p.stdout}, ensure_ascii=False, indent=2), encoding="utf-8")
        journal_data.update({"status": "failed", "returncode": p.returncode, "error_dump": str(error_dump)})
        journal.write_text(json.dumps(journal_data, ensure_ascii=False, indent=2), encoding="utf-8")
        die(f"minis-model-use failed with exit {p.returncode}; full output: {error_dump}", p.returncode)
    parsed = None
    try:
        parsed = parse_json_from_output(p.stdout)
    except Exception:
        parsed = None
    if isinstance(parsed, dict) and parsed.get("error"):
        detail = json.dumps(parsed, ensure_ascii=False)
        ambiguous = any(token in detail.lower() for token in ("http 502", "http 524", "timeout", "timed out", "connection reset"))
        status = "ambiguous_provider_error" if ambiguous else "failed"
        error_dump = WORKSPACE / ".image_gen_last_error.json"
        error_dump.write_text(json.dumps({**journal_data, "status": status, "raw_output": p.stdout, "parsed_error": parsed}, ensure_ascii=False, indent=2), encoding="utf-8")
        journal_data.update({"status": status, "error_dump": str(error_dump)})
        journal.write_text(json.dumps(journal_data, ensure_ascii=False, indent=2), encoding="utf-8")
        if ambiguous:
            die(f"provider returned an ambiguous error; do not retry automatically. Journal: {journal}", 3)
        die("image generation failed: " + detail, 2)
    if not output.exists() or output.stat().st_size == 0:
        journal_data.update({"status": "failed_no_output"})
        journal.write_text(json.dumps(journal_data, ensure_ascii=False, indent=2), encoding="utf-8")
        die(f"image generation did not produce output file: {output}", 2)
    dims = image_dimensions(output)
    if Image is not None and not dims:
        try:
            output.unlink()
        except OSError:
            pass
        die("provider output is not a decodable image; rejected and removed", 2)
    elapsed = format_elapsed(time.time() - started)
    pixel_size = f"{dims[0]}x{dims[1]}" if dims else str(payload.get("size"))
    aspect = aspect_from_dims(dims, fallback=str(payload.get("size")))
    tier = infer_tier(payload.get("quality"), pixel_size, payload.get("resolution"))
    journal_data.update({"status": "succeeded", "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "pixel_size": pixel_size, "path": str(output)})
    journal.write_text(json.dumps(journal_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "request": str(req),
        "journal": str(journal),
        "prompt_sha256": prompt_hash,
        "prompt_preserved": True,
        "model": model,
        "provider": provider,
        "site": provider or "OpenMinis image provider",
        "quality": payload.get("quality"),
        "resolution": payload.get("resolution"),
        "size": payload.get("size"),
        "aspect": aspect,
        "pixel_size": pixel_size,
        "tier": tier,
        "clarity": f"{pixel_size}, aspect={aspect}, quality={payload.get('quality')}",
        "elapsed": elapsed,
        "n": payload.get("n"),
        "path": str(output),
        "minis_url": minis_url(output),
    }, ensure_ascii=False, indent=2))


def build_common(args, selected_model):
    payload = {
        "model": selected_model,
        "size": args.size,
        "quality": args.quality,
        "n": args.n,
        "response_format": args.response_format,
    }
    # resolution is provider-specific; omit it unless explicitly requested.
    if args.resolution:
        payload["resolution"] = args.resolution
    if args.extra_body:
        try:
            extra = json.loads(args.extra_body)
        except json.JSONDecodeError as e:
            die(f"--extra-body must be a JSON object: {e}")
        if not isinstance(extra, dict):
            die("--extra-body must be a JSON object")
        payload.update(extra)
    return payload


def generate(args):
    model, provider = select_model(args.model, args.provider, args.allow_deprecated_provider)
    if provider in IMAGE_TOOL_PROVIDERS:
        # Do not include top-level prompt/size/n: model-use interprets those as
        # /images/generations, whose Picpi response may contain no extractable
        # image. The tool request is verified to return a real media file.
        request_text = args.prompt
        if args.size and args.size != "auto":
            request_text += f"\nRequested output aspect ratio or size: {args.size}."
        if args.n > 1:
            request_text += f"\nGenerate exactly {args.n} distinct images."
        payload = {
            "messages": [{"role": "user", "content": request_text}],
            "tools": [{"type": "image_generation"}],
            "tool_choice": "required",
        }
    else:
        payload = build_common(args, model)
        payload["prompt"] = args.prompt
    output = validate_output_path(args.output) if args.output else out_path("image_gen")
    run_model_use(payload, output, provider, model, args.timeout, args.prompt)


def edit(args):
    model, provider = select_model(args.model, args.provider, args.allow_deprecated_provider)
    if len(args.image) > 16:
        die("At most 16 reference images are supported")
    for img in args.image:
        p = Path(img)
        if not p.exists() or not p.is_file():
            die(f"image not found: {img}")
        if p.stat().st_size > 50 * 1024 * 1024:
            die(f"reference image exceeds 50 MiB: {img}")
        if Image is not None:
            try:
                with Image.open(p) as ref:
                    ref.verify()
            except Exception:
                die(f"reference is not a decodable image: {img}")
    prepared = [prepare_reference_image(img, args.ref_max_side, args.ref_quality) for img in args.image]
    data_uris = [image_data_uri(img) for img in prepared]
    if provider in IMAGE_TOOL_PROVIDERS:
        request_text = args.prompt
        if args.size and args.size != "auto":
            request_text += f"\nRequested output aspect ratio or size: {args.size}."
        if args.n > 1:
            request_text += f"\nGenerate exactly {args.n} distinct edited images."
        payload = {
            "messages": [{"role": "user", "content": request_text}],
            # OpenMinis accepts local references through this top-level field.
            # Do not use public URLs or Responses input_image objects here.
            "images": data_uris,
            "tools": [{"type": "image_generation"}],
            "tool_choice": "required",
        }
    else:
        payload = build_common(args, model)
        payload.update({
            "prompt": args.prompt,
            "images": data_uris,
        })
    output = validate_output_path(args.output) if args.output else out_path("image_edit")
    run_model_use(payload, output, provider, model, args.timeout, args.prompt)


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
    common.add_argument("--allow-deprecated-provider", action="store_true", help="Allow explicit use of a retired provider; never enabled automatically")
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
