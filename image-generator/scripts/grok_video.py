#!/usr/bin/env python3
"""grok2api 视频通道 CLI（grok-imagine-video）。

异步：create 只返回 request_id，须轮询 GET /v1/videos/{id}。
协议实测见 references/grok2api-video.md。

用法：
  grok_video.py gen --prompt "..." [--duration 8] [--ratio 16:9] [--resolution 720p]
                    [--image-url U | --ref-image U ...] [--no-wait] [--out DIR] [--json]
  grok_video.py status --id <request_id>
  grok_video.py wait --id <id> [--download] [--timeout 900] [--interval 5]
  grok_video.py edit   --prompt "..." --video-url URL
  grok_video.py extend --prompt "..." --video-url URL
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grok_image as gi

BASE = gi.DEFAULT_BASE
DEFAULT_MODEL = "grok-imagine-video"
RATIOS = ("1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3")
RESOLUTIONS = ("480p", "720p", "1080p")


def api(method, path, key, payload=None, timeout=300):
    url = path if path.startswith("http") else BASE + path
    _code, _elapsed, data = gi.request(method, url, key, payload, timeout)
    return data


def build_create(args):
    body = {"model": args.model, "prompt": args.prompt}
    if args.duration is not None:
        body["duration"] = args.duration
    if args.ratio:
        body["aspect_ratio"] = args.ratio
    if args.resolution:
        body["resolution"] = args.resolution
    if args.image_url:
        # image 与参考图/参考音互斥：显式给 image 时丢弃参考项（服务端会 400）
        body["image"] = {"url": args.image_url}
    else:
        if args.ref_image:
            body["reference_images"] = [{"url": u} for u in args.ref_image]
        if args.ref_audio:
            body["reference_audios"] = [{"voice_id": v} for v in args.ref_audio]
    return body


def validate(body):
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise SystemExit("prompt 不能为空")
    if body.get("duration") is not None and not (1 <= int(body["duration"]) <= 15):
        raise SystemExit("duration 须在 1–15 秒之间（web 路由实测恒出 6 秒）")
    ratio = body.get("aspect_ratio")
    if ratio is not None and ratio not in RATIOS:
        raise SystemExit("aspect_ratio 只接受 %s，收到 %s" % ("/".join(RATIOS), ratio))
    res = body.get("resolution")
    if res is not None and res not in RESOLUTIONS:
        raise SystemExit("resolution 只接受 %s，收到 %s" % ("/".join(RESOLUTIONS), res))
    if body.get("image") and (body.get("reference_images") or body.get("reference_audios")):
        raise SystemExit("image 与 reference_images/reference_audios 不能同时使用")
    refs = body.get("reference_images") or []
    if len(refs) > 8:
        raise SystemExit("reference_images 最多 8 张，收到 %d" % len(refs))
    auds = body.get("reference_audios") or []
    if len(auds) > 3:
        raise SystemExit("reference_audios 最多 3 个，收到 %d" % len(auds))
    video = body.get("video")
    if video is not None and not (video.get("url") or video.get("file_id")):
        raise SystemExit("video 需要 url 或 file_id")

def poll(job_id, key, timeout=900, interval=5, verbose=True):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        data = api("GET", "/v1/videos/" + job_id, key, None, 60)
        st = str(data.get("status", "")).lower()
        last = data
        if verbose:
            print("  status=%s progress=%s" % (st, data.get("progress")), file=sys.stderr)
        if st in ("done", "completed", "succeeded", "success", "failed", "error", "cancelled"):
            return data
        time.sleep(interval)
    last = dict(last or {})
    last["_timeout"] = True
    return last


def video_url(data):
    v = data.get("video") or {}
    return v.get("url") or data.get("url") or ""


def download(url, key, out_dir, stem):
    """下载视频到本地，返回 {path,bytes}。视频不走图片的尺寸校验。"""
    if not url:
        raise SystemExit("任务无可用视频地址")
    req = gi.urllib.request.Request(
        url, headers={"Authorization": "Bearer " + key, "User-Agent": gi.UA})
    with gi.urllib.request.urlopen(req, timeout=300) as resp:
        blob = resp.read()
    if len(blob) < 10240:
        raise SystemExit("下载内容过小（%dB），不当作视频" % len(blob))
    if blob[4:8] != b"ftyp":
        raise SystemExit("返回内容不是 MP4（缺 ftyp）")
    out_dir = out_dir or "/var/minis/attachments"
    os.makedirs(out_dir, exist_ok=True)
    path = gi.unique_path(out_dir, stem, "mp4")
    with open(path, "wb") as fh:
        fh.write(blob)
    return {"path": path, "bytes": len(blob)}


def cmd_gen(args):
    key = gi.load_key(args.key_file)
    body = build_create(args)
    validate(body)
    if args.resolution and args.resolution != "720p":
        print("  注意：当前账号池走 grok_web，实测只吃 720p —— 480p 会 503、1080p 会 400",
              file=sys.stderr)
    if args.image_url or args.ref_image:
        print("  注意：图生视频在 grok_web 路由不可用，需 Build/Console 账号", file=sys.stderr)
    created = api("POST", "/v1/videos/generations", key, body)
    job = created.get("request_id") or created.get("id")
    out = {"http": 200, "request_id": job, "model": args.model}
    print(json.dumps(out, ensure_ascii=False), file=sys.stderr)
    if not job:
        print(json.dumps(created, ensure_ascii=False))
        return 2
    if args.no_wait:
        print(json.dumps(out, ensure_ascii=False))
        return 0
    t0 = time.time()
    data = poll(job, key, args.timeout, args.interval, not args.json)
    out["elapsed_s"] = round(time.time() - t0, 1)
    out["status"] = data.get("status")
    if data.get("status", "").lower() in ("failed", "error", "cancelled") or data.get("_timeout"):
        out["error"] = data.get("error") or "timeout"
        print(json.dumps(out, ensure_ascii=False))
        return 1
    url = video_url(data)
    out["url"] = url
    if url:
        out.update(download(url, key, args.out, args.name or "grok-video"))
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_status(args):
    key = gi.load_key(args.key_file)
    print(json.dumps(api("GET", "/v1/videos/" + args.id, key, None, 60), ensure_ascii=False))
    return 0


def cmd_wait(args):
    key = gi.load_key(args.key_file)
    data = poll(args.id, key, args.timeout, args.interval, True)
    out = {"request_id": args.id, "status": data.get("status")}
    url = video_url(data)
    if url:
        out["url"] = url
        if args.download:
            out.update(download(url, key, args.out, args.name or "grok-video"))
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["status"] and not data.get("_timeout") else 1


def _media_cmd(args, path):
    key = gi.load_key(args.key_file)
    body = {"model": args.model, "prompt": args.prompt, "video": {"url": args.video_url}}
    if getattr(args, "duration", None):
        body["duration"] = args.duration
    created = api("POST", path, key, body)
    job = created.get("request_id") or created.get("id")
    if not job:
        print(json.dumps(created, ensure_ascii=False))
        return 2
    t0 = time.time()
    data = poll(job, key, args.timeout, args.interval, not args.json)
    out = {"request_id": job, "status": data.get("status"),
           "elapsed_s": round(time.time() - t0, 1)}
    url = video_url(data)
    if url:
        out["url"] = url
        out.update(download(url, key, args.out, args.name or "grok-video"))
    elif data.get("status", "").lower() in ("failed", "error"):
        out["error"] = data.get("error")
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("url") else 1


def cmd_edit(args):
    return _media_cmd(args, "/v1/videos/edits")


def cmd_extend(args):
    return _media_cmd(args, "/v1/videos/extensions")


def build_parser():
    p = argparse.ArgumentParser(description="grok2api 视频通道")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, wait_ok=True):
        sp.add_argument("--model", default=DEFAULT_MODEL)
        sp.add_argument("--key-file")
        sp.add_argument("--out", default="/var/minis/attachments")
        sp.add_argument("--name")
        sp.add_argument("--json", action="store_true")
        sp.add_argument("--timeout", type=int, default=900)
        sp.add_argument("--interval", type=int, default=5)

    g = sub.add_parser("gen", help="创建视频任务（默认等待并下载）")
    g.add_argument("--prompt", required=True)
    g.add_argument("--duration", type=int)
    g.add_argument("--ratio", choices=RATIOS)
    g.add_argument("--resolution", choices=RESOLUTIONS)
    g.add_argument("--image-url")
    g.add_argument("--ref-image", action="append")
    g.add_argument("--ref-audio", action="append")
    g.add_argument("--no-wait", dest="no_wait", action="store_true")
    common(g)
    g.set_defaults(func=cmd_gen)

    s = sub.add_parser("status", help="查询任务")
    s.add_argument("--id", required=True)
    s.add_argument("--key-file")
    s.set_defaults(func=cmd_status)

    w = sub.add_parser("wait", help="轮询任务")
    w.add_argument("--id", required=True)
    w.add_argument("--download", action="store_true")
    common(w)
    w.set_defaults(func=cmd_wait)

    for name, fn in (("edit", cmd_edit), ("extend", cmd_extend)):
        e = sub.add_parser(name, help="%s 视频" % name)
        e.add_argument("--prompt", required=True)
        e.add_argument("--video-url", required=True)
        e.add_argument("--duration", type=int)
        common(e)
        e.set_defaults(func=fn)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except gi.urllib.error.HTTPError as e:
        print(json.dumps({"http": e.code, "error": e.read().decode()[:500]}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
