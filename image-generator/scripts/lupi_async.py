#!/usr/bin/env python3
"""噜皮生图（image.mlgb7.com）异步任务通道。

提交即返回 202 + task_id，随后按 task_id 查询。用于长耗时 / 高并发 / 断线续查，
与 openminis_image.py（同步通道）互补。

两种传输（--transport）：
  direct    直连 HTTP，需要 key（--key-file > $LUPI_API_KEY > shared 凭据文件）
  provider  经 App 已配置的供应商发请求（minis-model-use passthrough），**不需要明文 key**
  auto      有 key 走 direct，否则走 provider（默认）

  provider 模式只支持 JSON 端点（generate / poll / list / cancel）；
  编辑（multipart）必须 direct。

用法：
  lupi_async.py submit --mode generate --prompt "..." [--size 1024x1024] [--n 1]
  lupi_async.py submit --mode edit --prompt "..." --image a.png      # 仅 direct
  lupi_async.py poll   --ids api_gen_xxx[,api_edit_yyy]
  lupi_async.py wait   --id api_gen_xxx [--timeout 600] [--download]
  lupi_async.py list   [--limit 20]
  lupi_async.py cancel --id api_gen_xxx

任何输出都不回显 key。submit 默认生成新的 Idempotency-Key；重试必须 --idempotency-key 复用。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

BASE = "https://image.mlgb7.com"
DEFAULT_KEY_FILE = "/var/minis/shared/image-gen/lupi-api-key.txt"
UA = "curl/8.5.0"  # 结果图直链拒绝 Python-urllib 默认 UA（403）
TERMINAL_TRUE = {"success", "succeeded", "failed", "error", "cancelled", "canceled"}
DEFAULT_PROVIDER_MODEL = "噜皮生图/gpt-image-2"  # <instance_label>/<model_id>


class Ctx:
    def __init__(self, transport: str, key: str | None, provider_model: str):
        self.transport = transport
        self.key = key
        self.provider_model = provider_model


def resolve_key(args) -> str | None:
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
    return None


def build_ctx(args) -> Ctx:
    key = resolve_key(args)
    t = args.transport
    if t == "auto":
        t = "direct" if key else "provider"
    if t == "direct" and not key:
        sys.exit(json.dumps({"ok": False, "error": "missing_credential",
                             "hint": "$LUPI_API_KEY / " + DEFAULT_KEY_FILE +
                                     "（或改用 --transport provider）"}, ensure_ascii=False))
    return Ctx(t, key, args.provider_model)


def _direct(url: str, data: bytes | None, headers: dict, timeout: int):
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:  # 连接层失败：结构化返回，不抛栈
        return -1, json.dumps({"transport_error": str(e.reason)[:200]}).encode()


def _provider(ctx: Ctx, path: str, method: str, body: dict | None,
              headers: dict | None, timeout: int):
    payload = {"passthrough": {"endpoint": path, "method": method, "body_mode": "replace"}}
    if body is not None:
        payload["passthrough"]["body"] = body
    if headers:
        payload["passthrough"]["headers"] = {k: v for k, v in headers.items()
                                             if k.lower() != "content-type"}
    with tempfile.TemporaryDirectory(prefix="lupi-pv-") as td:
        inp, out = os.path.join(td, "in.json"), os.path.join(td, "out.bin")
        with open(inp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        cp = subprocess.run(["minis-model-use", "run", "--model", ctx.provider_model,
                             "--input", inp, "--output", out],
                            capture_output=True, text=True, timeout=timeout + 60)
        if cp.returncode != 0:
            return -1, json.dumps({"transport_error": (cp.stderr or cp.stdout)[-300:]}).encode()
        try:
            meta = json.loads(cp.stdout)
        except Exception:
            return -1, json.dumps({"transport_error": cp.stdout[-300:]}).encode()
        status = meta.get("http_status", -1)
        raw = b""
        if os.path.exists(out):
            with open(out, "rb") as f:
                raw = f.read()
        if not raw and meta.get("content"):
            raw = str(meta["content"]).encode()
        return status, raw


def call(ctx: Ctx, path: str, method: str = "GET", body: dict | None = None,
         headers: dict | None = None, timeout: int = 120):
    if ctx.transport == "provider":
        return _provider(ctx, path, method, body, headers, timeout)
    data = json.dumps(body).encode() if body is not None else None
    h = {"User-Agent": UA, "Accept": "application/json",
         "Authorization": f"Bearer {ctx.key}"}
    if data is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    return _direct(BASE + path, data, h, timeout)


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


def cmd_submit(a, ctx: Ctx) -> dict:
    iid = a.idempotency_key or ("bf-" + uuid.uuid4().hex)
    common = {"model": a.model, "prompt": a.prompt, "n": str(a.n),
              "response_format": "url", "async": "true"}
    if a.size:
        common["size"] = a.size
    if a.quality:
        common["quality"] = a.quality
    t0 = time.time()
    if a.mode == "edit":
        if not a.image:
            return {"ok": False, "error": "edit_requires_image"}
        if ctx.transport != "direct":
            return {"ok": False, "error": "edit_needs_direct_transport",
                    "hint": "multipart 只能直连；provider 模式请改用 generate 或 minis-model-use 图片编辑"}
        body, ctype = multipart(common, [("image", p) for p in a.image])
        status, raw = _direct(f"{BASE}/v1/images/edits", body,
                              {"Authorization": f"Bearer {ctx.key}", "User-Agent": UA,
                               "Idempotency-Key": iid, "Content-Type": ctype}, a.timeout)
    else:
        status, raw = call(ctx, "/v1/images/generations", "POST", common,
                           {"Idempotency-Key": iid}, a.timeout)
    elapsed = round(time.time() - t0, 2)
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        payload = {"raw_head": raw[:200].decode("utf-8", "replace")}
    out = {"ok": status in (200, 202), "http": status, "elapsed": elapsed,
           "idempotency_key": iid, "mode": a.mode, "transport": ctx.transport}
    if 200 <= status < 300:
        out["task_id"] = payload.get("task_id") or payload.get("id")
        out["status"] = payload.get("status")
        out["poll_url"] = payload.get("poll_url") or f"{BASE}/api/image-tasks?ids={out.get('task_id')}"
        if out.get("task_id") is None:
            out["sync_payload_keys"] = sorted(payload.keys())
            out["payload"] = payload
    else:
        out["error"] = payload
    return out


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
        "created_at": item.get("created_at"),
        "error_code": item.get("error_code") or "",
        "public_error": item.get("public_error") or "",
        "images": [{"url": r.get("url") or r.get("path"), "width": r.get("width"),
                    "height": r.get("height"), "revised_prompt": r.get("revised_prompt", "")}
                   for r in results],
    }


def _items(ctx: Ctx, path: str, timeout: int = 60) -> dict:
    status, raw = call(ctx, path, timeout=timeout)
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return {"ok": False, "http": status, "raw_head": raw[:200].decode("utf-8", "replace")}
    if not (200 <= status < 300):
        return {"ok": False, "http": status, "error": payload}
    return {"ok": True, "http": status,
            "items": [summarize(i) for i in payload.get("items", [])]}


def cmd_poll(a, ctx: Ctx) -> dict:
    r = _items(ctx, f"/api/image-tasks?ids={a.ids}", a.timeout)
    if r.get("ok"):
        r["count"] = len(r["items"])
    return r


def cmd_list(a, ctx: Ctx) -> dict:
    r = _items(ctx, f"/api/image-tasks?limit={a.limit}", a.timeout)
    if r.get("ok"):
        r["count"] = len(r["items"])
    return r


def cmd_cancel(a, ctx: Ctx) -> dict:
    status, raw = call(ctx, f"/api/image-tasks/{a.id}/cancel", "POST", {"reason": "user"})
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        payload = {"raw_head": raw[:200].decode("utf-8", "replace")}
    if 200 <= status < 300 and isinstance(payload, dict):
        return {"ok": True, "http": status, "task": summarize(payload)}
    return {"ok": False, "http": status, "error": payload,
            "note": "终态任务通常不接受取消；已成功的图仍可由 results 取回"}


def download(url: str, output: str) -> dict:
    if os.path.exists(output):
        return {"ok": False, "error": "output_exists", "path": output}
    status, raw = _direct(url, None, {"User-Agent": UA}, 180)
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


def _targets(a, item: dict) -> list[str]:
    """多图落盘命名：--output 给基名时按 -1/-2 编号；否则 <id>-<n>.png。"""
    n = max(1, len(item["images"]))
    out = []
    for idx in range(n):
        if a.output:
            stem, ext = os.path.splitext(os.path.basename(a.output))
            name = f"{stem}{'' if n == 1 else '-' + str(idx + 1)}{ext or '.png'}"
        else:
            name = f"{item['id']}.png" if n == 1 else f"{item['id']}-{idx + 1}.png"
        out.append(os.path.join(a.out_dir, name))
    return out


def cmd_wait(a, ctx: Ctx) -> dict:
    deadline = time.time() + a.timeout
    interval = a.interval
    last = None
    while True:
        r = _items(ctx, f"/api/image-tasks?ids={a.id}")
        if r.get("ok") and r.get("items"):
            item = r["items"][0]
            last = item
            if item["terminal"]:
                out = {"ok": item["status"] in ("success", "succeeded"), "task": item,
                       "timed_out": False}
                if a.download and item["images"]:
                    out["files"] = [download(im["url"], tgt)
                                    for im, tgt in zip(item["images"], _targets(a, item))]
                return out
        if time.time() >= deadline:
            return {"ok": False, "timed_out": True, "ambiguous": True, "last": last,
                    "note": "超时不代表远端失败；用同一 task_id 续查，勿重复提交"}
        time.sleep(interval)
        interval = min(interval * 1.5, 20)


def main() -> None:
    ap = argparse.ArgumentParser(description="lupi async image tasks")
    ap.add_argument("--key-file")
    ap.add_argument("--transport", choices=["auto", "direct", "provider"], default="auto")
    ap.add_argument("--provider-model", default=DEFAULT_PROVIDER_MODEL,
                    help="provider 传输用的 App 模型，形如 <instance_label>/<model_id>")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("submit")
    s.add_argument("--mode", choices=["generate", "edit"], default="generate")
    s.add_argument("--prompt", required=True)
    s.add_argument("--model", default="gpt-image-2")
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
    w.add_argument("--output", help="附件文件名，落地到 --out-dir（多图自动编号）")
    w.add_argument("--out-dir", default="/var/minis/attachments")

    l = sub.add_parser("list")
    l.add_argument("--limit", type=int, default=20)
    l.add_argument("--timeout", type=int, default=60)

    c = sub.add_parser("cancel")
    c.add_argument("--id", required=True)

    a = ap.parse_args()
    ctx = build_ctx(a)
    fn = {"submit": cmd_submit, "poll": cmd_poll, "wait": cmd_wait,
          "list": cmd_list, "cancel": cmd_cancel}[a.cmd]
    print(json.dumps(fn(a, ctx), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
