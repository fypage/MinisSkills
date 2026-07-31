#!/usr/bin/env python3
"""Recover an already-generated minis:// image through browser canvas.

This never calls an image model. It is a compatibility fallback for Minis
installations where a media URL opens in WebView but its attachment path is
not readable from the Linux sandbox.
"""
import argparse
import base64
import json
import re
import subprocess
import sys
import time
from pathlib import Path

MIN_B64 = 1000


def run(args, timeout=120):
    return subprocess.run(args, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=timeout)


def json_objects(text):
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


def envelope_text(raw):
    objs = json_objects(raw)
    if objs:
        data = objs[-1].get("data") or {}
        return data.get("text") or ""
    return raw.strip()


def offload_candidates(raw):
    found = []
    for pat in (r"minis://offloads/([^\s\"']+)",
                r"(/var/minis/offloads/[^\s\"']+)"):
        for hit in re.findall(pat, raw):
            p = Path("/var/minis/offloads") / hit if not hit.startswith("/") else Path(hit)
            if p not in found:
                found.append(p)
    return found


def data_url_from_output(raw):
    texts = [envelope_text(raw), raw]
    for p in offload_candidates(raw):
        try:
            content = p.read_text(encoding="utf-8")
            texts.extend([envelope_text(content), content])
        except OSError:
            pass
    for text in texts:
        match = re.search(r"data:image/(?:png|jpeg|webp);base64,([A-Za-z0-9+/=\r\n]+)", text)
        if match:
            b64 = re.sub(r"\s+", "", match.group(1))
            if len(b64) > MIN_B64:
                return b64
    return None


def tab_id_from_output(raw):
    match = re.search(r"tab(?:_id|\s+)(?::|=)?\s*(\d+)", raw, re.I)
    return match.group(1) if match else None


def recover(minis_url, output, attempts=15):
    target = Path(output)
    opened = run(["minis-browser-use", "new_tab", "--url", minis_url], 30)
    if opened.returncode:
        return False, "browser could not open media URL"
    tab = tab_id_from_output(opened.stdout)
    common = ["--tab-id", tab] if tab is not None else []
    script = ("var i=document.querySelector('img');"
              "if(!i||!i.complete||!i.naturalWidth)return 'NOT_READY';"
              "var c=document.createElement('canvas');"
              "c.width=i.naturalWidth;c.height=i.naturalHeight;"
              "c.getContext('2d').drawImage(i,0,0);"
              "return c.toDataURL('image/png');")
    try:
        for _ in range(attempts):
            result = run(["minis-browser-use", "execute_js", *common,
                          "--script", script], 120)
            if result.returncode == 0:
                b64 = data_url_from_output(result.stdout)
                if b64:
                    try:
                        raw = base64.b64decode(b64, validate=True)
                    except Exception:
                        raw = b""
                    if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) > 2048:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(raw)
                        return True, f"recovered {len(raw)} bytes"
            time.sleep(0.5)
        return False, "canvas extraction returned no valid image"
    finally:
        close = ["minis-browser-use", "close_tab"]
        if tab is not None:
            close += ["--tab-id", tab]
        run(close, 15)


def main():
    p = argparse.ArgumentParser(description="Recover an existing minis:// image without regenerating")
    p.add_argument("--url", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--attempts", type=int, default=15)
    args = p.parse_args()
    ok, message = recover(args.url, args.output, args.attempts)
    print(json.dumps({"status": "ok" if ok else "error", "recovered": ok,
                      "url": args.url, "path": args.output, "message": message},
                     ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
