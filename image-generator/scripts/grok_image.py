#!/usr/bin/env python3
"""grok2api 图片通道 CLI（同步协议，实测于 v3.1.6 / 2026-10-17）。

用法:
  grok_image.py models
  grok_image.py gen --prompt "..." [--model grok-imagine-image-2.0] [--ratio 2:3 | --size 1024x1536]
                    [--n 1] [--resolution 1k|2k] [--quality low|medium] [--format url|b64_json]
                    [--out DIR] [--json] [--timeout 300]
  grok_image.py edit --prompt "..." --image-url URL[,URL...] [--model grok-imagine-image-edit]
                     [--ratio 1:1] [--out DIR] [--json]
  grok_image.py get --url URL --out FILE

鉴权: $GROK2API_KEY，或 --key-file，或 /var/minis/shared/grok2api/admin.txt 的 CLIENT_KEY 行。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://grok.a18016.ccwu.cc"
DEFAULT_KEYRING = "/var/minis/shared/grok2api/admin.txt"
UA = "curl/8.5.0"
RATIOS = {"auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3",
          "2:1", "1:2", "19.5:9", "9:19.5", "20:9", "9:20"}


class GrokError(RuntimeError):
    pass


def load_key(path=None):
    key = os.environ.get("GROK2API_KEY", "").strip()
    if key:
        return key
    candidates = [path] if path else [DEFAULT_KEYRING]
    for p in candidates:
        if not p or not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                m = re.search(r"CLIENT_KEY[^:]*:\s*(\S+)", line)
                if m:
                    return m.group(1)
    raise GrokError("缺少 API Key：请设 $GROK2API_KEY 或传 --key-file")


def request(method, url, key, payload=None, timeout=300):
    data = None
    headers = {"Authorization": "Bearer " + key, "User-Agent": UA}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            code = resp.status
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:600].decode("utf-8", "replace")
        raise GrokError(f"HTTP {exc.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GrokError(f"网络失败（结果不确定，勿盲目重发）: {exc}") from None
    elapsed = round(time.time() - started, 1)
    try:
        return code, elapsed, json.loads(raw)
    except ValueError:
        raise GrokError(f"非 JSON 响应 ({code}): {raw[:300]!r}") from None


def image_size(data):
    """返回 (width, height, fmt)，纯 Python 解析 JPEG/PNG/WEBP 头。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return w, h, "PNG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return None, None, "WEBP"
    if data[:2] == b"\xff\xd8":
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h, "JPEG"
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
        return None, None, "JPEG"
    return None, None, "unknown"


def unique_path(directory, stem, ext):
    os.makedirs(directory, exist_ok=True)
    candidate = os.path.join(directory, f"{stem}.{ext}")
    index = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{stem}-{index}.{ext}")
        index += 1
    return candidate


def fetch(url, key, out_dir, stem):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + key, "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            blob = resp.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GrokError(f"下载图片失败: {exc}") from None
    if len(blob) < 1024:
        raise GrokError(f"下载内容过小（{len(blob)}B），不当作图片")
    width, height, fmt = image_size(blob)
    ext = {"JPEG": "jpg", "PNG": "png"}.get(fmt, "bin")
    path = unique_path(out_dir, stem, ext)
    with open(path, "wb") as fh:
        fh.write(blob)
    return {"path": path, "bytes": len(blob), "width": width, "height": height, "format": fmt}


def save_items(items, key, out_dir, stem, timeout):
    results = []
    for idx, item in enumerate(items):
        suffix = "" if len(items) == 1 else f"-{idx + 1}"
        if item.get("b64_json"):
            blob = base64.b64decode(item["b64_json"])
            width, height, fmt = image_size(blob)
            ext = {"JPEG": "jpg", "PNG": "png"}.get(fmt, "bin")
            path = unique_path(out_dir, stem + suffix, ext)
            with open(path, "wb") as fh:
                fh.write(blob)
            results.append({"path": path, "bytes": len(blob), "width": width,
                            "height": height, "format": fmt, "url": None})
        else:
            url = item.get("url") or ""
            if not url:
                raise GrokError("响应里既无 url 也无 b64_json")
            info = fetch(url, key, out_dir, stem + suffix)
            info["url"] = url
            results.append(info)
    return results


def cmd_models(args):
    key = load_key(args.key_file)
    _, _, data = request("GET", args.base.rstrip("/") + "/v1/models", key, timeout=args.timeout)
    ids = [m.get("id") for m in data.get("data", [])]
    for mid in ids:
        print(mid)
    return 0


def build_generation(args):
    body = {"model": args.model, "prompt": args.prompt, "n": args.n}
    if args.ratio:
        if args.ratio not in RATIOS:
            raise GrokError(f"aspect_ratio 不受支持: {args.ratio}（可选 {sorted(RATIOS)}）")
        body["aspect_ratio"] = args.ratio
    if args.size:
        body["size"] = args.size
    if args.resolution:
        body["resolution"] = args.resolution
    if args.quality:
        body["quality"] = args.quality
    if args.format:
        body["response_format"] = args.format
    return body


def cmd_gen(args):
    key = load_key(args.key_file)
    body = build_generation(args)
    if args.format == "b64_json" and args.n > 1:
        raise GrokError("b64_json 建议 n=1，避免单响应体积过大")
    code, elapsed, data = request("POST", args.base.rstrip("/") + "/v1/images/generations",
                                  key, body, timeout=args.timeout)
    items = data.get("data") or []
    if not items:
        raise GrokError(f"响应无 data: {json.dumps(data)[:300]}")
    stem = args.name or ("grok-" + time.strftime("%Y%m%d-%H%M%S"))
    saved = save_items(items, key, args.out, stem, args.timeout)
    report = {"http": code, "elapsed_s": elapsed, "model": args.model,
              "requested": {k: body[k] for k in ("aspect_ratio", "size", "n", "resolution", "quality") if k in body},
              "mime": items[0].get("mime_type"), "images": saved}
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"http={code} elapsed={elapsed}s n={len(saved)}")
        for s in saved:
            print(f"{s['path']}  {s['bytes']}B  {s['width']}x{s['height']}  {s['format']}")
    return 0


def cmd_edit(args):
    key = load_key(args.key_file)
    urls = [u.strip() for u in args.image_url.split(",") if u.strip()]
    if not urls:
        raise GrokError("--image-url 至少给一个公网可达 URL")
    if len(urls) > 8:
        raise GrokError("编辑最多 8 张参考图")
    body = {"model": args.model, "prompt": args.prompt, "n": args.n,
            "images": [{"url": u} for u in urls]}
    if args.ratio:
        body["aspect_ratio"] = args.ratio
    if args.format:
        body["response_format"] = args.format
    code, elapsed, data = request("POST", args.base.rstrip("/") + "/v1/images/edits",
                                  key, body, timeout=args.timeout)
    items = data.get("data") or []
    if not items:
        raise GrokError(f"响应无 data: {json.dumps(data)[:300]}")
    stem = args.name or ("grok-edit-" + time.strftime("%Y%m%d-%H%M%S"))
    saved = save_items(items, key, args.out, stem, args.timeout)
    report = {"http": code, "elapsed_s": elapsed, "model": args.model, "images": saved}
    print(json.dumps(report, ensure_ascii=False) if args.json else
          f"http={code} elapsed={elapsed}s n={len(saved)}\n" +
          "\n".join(f"{s['path']}  {s['bytes']}B  {s['width']}x{s['height']}" for s in saved))
    return 0


def cmd_get(args):
    key = load_key(args.key_file)
    info = fetch(args.url, key, os.path.dirname(os.path.abspath(args.out)) or ".",
                 os.path.splitext(os.path.basename(args.out))[0])
    os.replace(info["path"], args.out)
    info["path"] = args.out
    print(json.dumps(info, ensure_ascii=False))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="grok2api 图片通道")
    parser.add_argument("--base", default=os.environ.get("GROK2API_BASE", DEFAULT_BASE))
    parser.add_argument("--key-file", default=None)
    parser.add_argument("--timeout", type=int, default=300)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("models")

    gen = sub.add_parser("gen")
    gen.add_argument("--prompt", required=True)
    gen.add_argument("--model", default="grok-imagine-image-2.0")
    gen.add_argument("--ratio", default=None)
    gen.add_argument("--size", default=None)
    gen.add_argument("--resolution", default=None)
    gen.add_argument("--quality", default=None)
    gen.add_argument("--format", default="url")
    gen.add_argument("--n", type=int, default=1)
    gen.add_argument("--out", default="/var/minis/attachments")
    gen.add_argument("--name", default=None)
    gen.add_argument("--json", action="store_true")

    edit = sub.add_parser("edit")
    edit.add_argument("--prompt", required=True)
    edit.add_argument("--image-url", required=True)
    edit.add_argument("--model", default="grok-imagine-image-edit")
    edit.add_argument("--ratio", default=None)
    edit.add_argument("--format", default="url")
    edit.add_argument("--n", type=int, default=1)
    edit.add_argument("--out", default="/var/minis/attachments")
    edit.add_argument("--name", default=None)
    edit.add_argument("--json", action="store_true")

    get = sub.add_parser("get")
    get.add_argument("--url", required=True)
    get.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    handler = {"models": cmd_models, "gen": cmd_gen, "edit": cmd_edit, "get": cmd_get}[args.command]
    try:
        return handler(args)
    except GrokError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
