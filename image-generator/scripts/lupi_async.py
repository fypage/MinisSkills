#!/usr/bin/env python3
"""噜皮生图（image.mlgb7.com）异步任务通道。

提交即返回 202 + task_id，随后按 task_id 查询。用于长耗时 / 高并发 / 断线续查，
与 openminis_image.py（minis-model-use 同步通道）互补。

凭据解析顺序：--key-file > $LUPI_API_KEY > /var/minis/shared/image-gen/lupi-api-key.txt
任何输出都不回显 key。

用法：
  lupi_async.py submit --mode generate --prompt "..." [--size 1024x1024] [--n 1]
  lupi_async.py submit --mode edit --prompt "..." --image a.png [--image b.png]
  lupi_async.py poll   --ids api_gen_xxx[,api_edit_yyy]
  lupi_async.py wait   --id api_gen_xxx [--timeout 600] [--download --output out.png]

submit 默认生成新的 Idempotency-Key；网络重试时用 --idempotency-key 复用同一值。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = "https://image.mlgb7.com"
DEFAULT_KEY_FILE = "/var/minis/shared/image-gen/lupi-api-key.txt"
UA = "curl/8.5.0"  # 结果图直链拒绝 Python-urllib 默认 UA（403）
TERMINAL_TRUE = {"success", "succeeded", "failed", "error", "cancelled", "canceled"}


def resolve_key(args) -> str:
    if args.key_file:
        with open(args.key_file, "r", encoding="utf-8") as f:
            k = f.read().strip()
        if k:
            return k
    k = os.environ.get("LUPI_API_KEY", "").strip()
    if k:
        return k
    if os.path.exists(DEFAULT_KEY_FILE):
        with open(DEFAULT_KEY_FILE, "r", encoding="utf-8") as f:
            k = f.read().strip()
        if k:
            return k
    sys.exit(json.dumps({"ok": False, "error": "missing_credential",
                         "hint": "set $LUPI_API_KEY or write " + DEFAULT_KEY_FILE}, ensure_ascii=False))


def http(url: str, data: bytes | None = None, headers: dict | None = None, timeout: int = 120):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def multipart(fields: dict, files: list[tuple[str, str]]) -> tuple[bytes, str]:
    boundary = "----bf" + uuid.uuid4().hex
    out = bytearray()
    for k, v in fields.items():
        out += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    for name, path in files:
        fn = os.path.basename(path)
        ctype = mimetypes.guess_type(fn)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            blob = f.read()
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{fn}\"\r\n"
                f"Content-Type: {ctype}\r\n\r\n").encode() + blob + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def cmd_submit(a, key: str) -> dict:
    iid = a.idempotency_key or ("bf-" + uuid.uuid4().hex)
    common = {"model": a.model, "prompt": a.prompt, "n": str(a.n),
              "response_format": "url", "async": "true"}
    if a.size:
        common["size"] = a.size
    if a.quality:
        common["quality"] = a.quality
    headers = {"Authorization": f"Bearer {key}", "Idempotency-Key": iid,
               "User-Agent": UA, "Accept": "application/json"}
    if a.mode == "edit":
        if not a.image:
            sys.exit(json.dumps({"ok": False, "error": "edit_requires_image"}, ensure_ascii=False))
        body, ctype = multipart(common, [("image", p) for p in a.image])
        headers["Content-Type"] = ctype
        url, t0 = f"{BASE}/v1/images/edits", time.time()
    else:
        body = json.dumps(common).encode()
        headers["Content-Type"] = "application/json"
        url, t0 = f"{BASE}/v1/images/generations", time.time()
    status, raw = http(url, body, headers, timeout=a.timeout)
    elapsed = round(time.time() - t0, 2)
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        payload = {"raw_head": raw[:200].decode("utf-8", "replace")}
    out = {"ok": status in (200, 202), "http": status, "elapsed": elapsed,
           "idempotency_key": iid, "mode": a.mode}
    if 200 <= status < 300:
        out["task_id"] = payload.get("task_id") or payload.get("id")
        out["status"] = payload.get("status")
        out["poll_url"] = payload.get("poll_url") or f"{BASE}/api/image-tasks?ids={out.get('task_id')}"
        if out.get("task_id") is None:
            out["sync_payload_keys"] = sorted(payload.keys())  # 非异步响应，交回同步解析
            out["payload"] = payload
    else:
        out["error"] = payload
    return out


def fetch_tasks(ids: str, key: str, timeout: int = 60) -> dict:
    status, raw = http(f"{BASE}/api/image-tasks?ids={ids}",
                       headers={"Authorization": f"Bearer {key}", "User-Agent": UA,
                                "Accept": "application/json"}, timeout=timeout)
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return {"ok": False, "http": status, "raw_head": raw[:200].decode("utf-8", "replace")}
    return {"ok": 200 <= status < 300, "http": status, "payload": payload}


def summarize(item: dict) -> dict:
    results = item.get("results") or []
    return {
        "id": item.get("id"),
        "status": item.get("status"),
        "terminal": item.get("terminal", item.get("status") in TERMINAL_TRUE),
        "stage": item.get("stage_label") or item.get("stage_code"),
        "mode": item.get("mode"),
        "model": item.get("model"),
        "size_requested": item.get("size"),
        "requested_count": item.get("requested_count"),
        "succeeded_count": item.get("succeeded_count"),
        "failed_count": item.get("failed_count"),
        "elapsed_ms": item.get("elapsed_ms"),
        "error_code": item.get("error_code") or "",
        "public_error": item.get("public_error") or "",
        "images": [{"url": r.get("url") or r.get("path"), "width": r.get("width"),
                    "height": r.get("height"), "revised_prompt": r.get("revised_prompt", "")}
                   for r in results],
    }


def cmd_poll(a, key: str) -> dict:
    r = fetch_tasks(a.ids, key, timeout=a.timeout)
    if not r["ok"]:
        return r
    items = [summarize(i) for i in r["payload"].get("items", [])]
    return {"ok": True, "http": r["http"], "count": len(items), "items": items}


def download(url: str, output: str) -> dict:
    if os.path.exists(output):
        return {"ok": False, "error": "output_exists", "path": output}
    status, raw = http(url, headers={"User-Agent": UA}, timeout=180)
    if status != 200 or not raw:
        return {"ok": False, "error": "download_failed", "http": status}
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(raw))
        im.load()
        w, h = im.size
        fmt = im.format
    except Exception as e:  # 非图片内容一律拒收
        return {"ok": False, "error": "not_an_image", "detail": str(e)[:120],
                "sha256": hashlib.sha256(raw).hexdigest()[:16]}
    os.makedirs(os.path.dirname(output), exist_ok=True)
    tmp = output + ".part"
    with open(tmp, "wb") as f:
        f.write(raw)
    os.replace(tmp, output)
    return {"ok": True, "path": output, "bytes": len(raw), "format": fmt,
            "width": w, "height": h,
            "sha256": hashlib.sha256(raw).hexdigest()[:16]}


def cmd_wait(a, key: str) -> dict:
    deadline = time.time() + a.timeout
    interval = a.interval
    last = None
    while True:
        r = fetch_tasks(a.id, key)
        if r.get("ok") and r["payload"].get("items"):
            item = summarize(r["payload"]["items"][0])
            last = item
            if item["terminal"]:
                out = {"ok": item["status"] in ("success", "succeeded"), "task": item,
                       "timed_out": False}
                if a.download and item["images"]:
                    out["files"] = [download(im["url"], os.path.join(
                        a.out_dir, os.path.basename(a.output or (item["id"] + ".png"))))
                        for im in item["images"][:1]]
                return out
        if time.time() >= deadline:
            return {"ok": False, "timed_out": True, "ambiguous": True, "last": last,
                    "note": "超时不代表远端失败；用同一 task_id 续查，勿重复提交"}
        time.sleep(interval)
        interval = min(interval * 1.5, 20)


def main() -> None:
    ap = argparse.ArgumentParser(description="lupi async image tasks")
    ap.add_argument("--key-file")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("submit")
    s.add_argument("--mode", choices=["generate", "edit"], default="generate")
    s.add_argument("--prompt", required=True)
    s.add_argument("--model", default="gpt-image-2.5")
    s.add_argument("--size", default="1024x1024")
    s.add_argument("--quality", default="auto")
    s.add_argument("--n", type=int, default=1)
    s.add_argument("--image", action="append", default=[])
    s.add_argument("--idempotency-key")
    s.add_argument("--timeout", type=int, default=180)

    p = sub.add_parser("poll")
    p.add_argument("--ids", required=True, help="逗号分隔，可混合 api_gen_/api_edit_")
    p.add_argument("--timeout", type=int, default=60)

    w = sub.add_parser("wait")
    w.add_argument("--id", required=True)
    w.add_argument("--timeout", type=int, default=600)
    w.add_argument("--interval", type=int, default=5)
    w.add_argument("--download", action="store_true")
    w.add_argument("--output", help="附件文件名，落地到 --out-dir")
    w.add_argument("--out-dir", default="/var/minis/attachments")

    a = ap.parse_args()
    key = resolve_key(a)
    fn = {"submit": cmd_submit, "poll": cmd_poll, "wait": cmd_wait}[a.cmd]
    print(json.dumps(fn(a, key), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
