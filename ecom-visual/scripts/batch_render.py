#!/usr/bin/env python3
"""按 plan.json 串行调用 image-generator 通道出图，逐张验证落盘。

设计取舍（见 references/render.md）：
- 默认串行：付费通道并发上限各家不同，超限直接报错，串行最稳。
- 失败不重试：超时/断流属结果不确定，重试等于再买一张。
- 已存在即跳过（--force 才覆盖）。
- --dry-run 只打印命令，不花钱。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

WRAPPER = Path("/var/minis/skills/image-generator/scripts/openminis_image.py")

# 方法论比例 → OpenAI 系像素口径（像素以解码为准，请求值只是提示）
RATIO_TO_SIZE = {
    "1:1": "1024x1024",
    "2:3": "1024x1536",
    "4:5": "1024x1280",
    "3:4": "768x1024",
    "16:9": "1536x864",
    "9:16": "864x1536",
    "3:2": "1536x1024",
    "4:3": "1024x768",
}


def die(msg: str, code: int = 2):
    print(f"错误：{msg}", file=sys.stderr)
    raise SystemExit(code)


def load_plan(path: Path) -> dict:
    if not path.is_file():
        die(f"plan 文件不存在：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        die(f"plan 不是合法 JSON：{exc}")
    if not isinstance(data, dict) or "shots" not in data:
        die("plan 必须含 shots 数组")
    if not isinstance(data["shots"], list) or not data["shots"]:
        die("shots 为空")
    return data


def resolve_size(shot: dict) -> str:
    size = str(shot.get("size") or "").strip()
    if not size:
        ratio = str(shot.get("ratio") or "1:1").strip()
        if ratio not in RATIO_TO_SIZE:
            die(f"未知比例 {ratio!r}，可用：{', '.join(RATIO_TO_SIZE)}")
        return RATIO_TO_SIZE[ratio]
    if ":" in size:
        if size not in RATIO_TO_SIZE:
            die(f"未知比例 {size!r}，可用：{', '.join(RATIO_TO_SIZE)}")
        return RATIO_TO_SIZE[size]
    return size


def read_prompt(shot: dict, plan_dir: Path) -> str:
    if shot.get("prompt"):
        return str(shot["prompt"]).strip()
    rel = shot.get("prompt_file")
    if not rel:
        die(f"{shot.get('id', '?')}：缺少 prompt 或 prompt_file")
    path = (plan_dir / rel) if not Path(rel).is_absolute() else Path(rel)
    if not path.is_file():
        die(f"提示词文件不存在：{path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        die(f"提示词文件为空：{path}")
    return text


def build_cmd(shot: dict, prompt: str, size: str, out: Path,
              model: str, provider: str, quality: str, timeout: int,
              ref_image: str | None) -> list[str]:
    mode = "edit" if ref_image else "generate"
    cmd = [sys.executable, str(WRAPPER), mode]
    if ref_image:
        cmd += ["--image", ref_image]
    cmd += ["--prompt", prompt, "--size", size, "--quality", quality,
            "--n", "1", "--timeout", str(timeout), "--output", str(out)]
    if model:
        cmd += ["--model", model]
    if provider:
        cmd += ["--provider", provider]
    return cmd


def verify(path: Path) -> tuple[bool, str]:
    """只做真实性校验：存在、非空、可解码。像素以 Pillow 为准。"""
    if not path.is_file():
        return False, "未落盘"
    size = path.stat().st_size
    if size == 0:
        return False, "空文件"
    try:
        from PIL import Image
    except ImportError:
        return True, f"{size} 字节（无 Pillow，未解码校验）"
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            w, h = im.size
            fmt = im.format
    except Exception as exc:  # noqa: BLE001
        return False, f"解码失败：{exc}"
    return True, f"{fmt} {w}×{h}｜{size} 字节"


def main() -> None:
    ap = argparse.ArgumentParser(description="电商视觉整包串行出图")
    ap.add_argument("--plan", required=True, help="plan.json 路径")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--model", default="gpt-image-2")
    ap.add_argument("--provider", default="噜皮生图")
    ap.add_argument("--quality", default="auto")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--only", default="", help="只跑指定编号，逗号分隔，如 01,03")
    ap.add_argument("--force", action="store_true", help="覆盖已存在文件")
    ap.add_argument("--dry-run", action="store_true", help="只打印命令不执行")
    ap.add_argument("--jobs", type=int, default=1, help="并发数，默认 1（串行）")
    args = ap.parse_args()

    if args.jobs != 1:
        die("当前实现只支持串行（--jobs 1）；付费通道并发上限各家不同，超限会直接报错")

    plan_path = Path(args.plan).expanduser().resolve()
    plan = load_plan(plan_path)
    plan_dir = plan_path.parent
    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    ref_default = plan.get("reference_image")

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    shots = [s for s in plan["shots"] if not only or str(s.get("id")) in only]
    if not shots:
        die("筛选后没有要出的图")

    total = len(shots)
    ok, skipped, failed = [], [], []
    started = time.time()

    for idx, shot in enumerate(shots, 1):
        sid = str(shot.get("id") or f"{idx:02d}")
        slug = str(shot.get("file") or f"{sid}.png")
        out = out_dir / slug
        size = resolve_size(shot)
        prompt = read_prompt(shot, plan_dir)
        ref = shot.get("reference_image", ref_default)
        if ref and not Path(ref).is_file():
            print(f"[{idx}/{total}] {sid} 参考图不存在，忽略该图：{ref}", file=sys.stderr)
            ref = None

        print(f"[{idx}/{total}] {sid} {shot.get('use', '')}｜{size}｜提示词 {len(prompt)} 字")

        if out.exists() and not args.force:
            good, info = verify(out)
            print(f"  跳过（已存在）：{info}")
            skipped.append((sid, str(out)))
            continue

        cmd = build_cmd(shot, prompt, size, out, args.model, args.provider,
                        args.quality, args.timeout, ref)
        if args.dry_run:
            preview = prompt if len(prompt) <= 100 else prompt[:100] + "…"
            print(f"  DRY-RUN 尺寸 {size}｜prompt={preview!r}")
            continue

        t0 = time.time()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout + 120)
        except subprocess.TimeoutExpired:
            print("  失败：进程超时（结果不确定，不自动重试）", file=sys.stderr)
            failed.append((sid, "进程超时"))
            continue
        elapsed = time.time() - t0

        good, info = verify(out)
        if proc.returncode != 0 or not good:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            print(f"  失败：{info}｜退出码 {proc.returncode}", file=sys.stderr)
            if tail:
                print("  " + tail[-1][:300], file=sys.stderr)
            failed.append((sid, info))
            continue
        print(f"  完成：{info}｜耗时 {elapsed:.0f} 秒")
        ok.append((sid, str(out), info, elapsed))

    wall = time.time() - started
    print("\n" + "=" * 60)
    print(f"成功 {len(ok)}｜跳过 {len(skipped)}｜失败 {len(failed)}｜总耗时 {wall:.0f} 秒")
    for sid, path, info, el in ok:
        print(f"  ✓ {sid}  {info}  {el:.0f}s  {path}")
    for sid, path in skipped:
        print(f"  = {sid}  已存在  {path}")
    for sid, why in failed:
        print(f"  ✗ {sid}  {why}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
