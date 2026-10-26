#!/usr/bin/env python3
"""参考图粗测：取主色簇 hex、明暗分布、主体外接框，供反推时量化用。

只做统计，不做审美判断。输出是给 Style Lock 填 hex 和百分比的起点，
最终色值与占比仍需人眼确认（尤其白底图的主色簇会被背景淹没）。

用法：
  python3 analyze_ref.py --image ref.jpg --colors 5
  python3 analyze_ref.py --image ref.jpg --colors 5 --json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter


def die(msg: str) -> None:
    print(f"错误：{msg}", file=sys.stderr)
    raise SystemExit(2)


def quantize(img, bins: int = 4):
    small = img.convert("RGB").resize((160, 160))
    px = list(small.getdata())
    step = 256 // bins
    buckets = Counter()
    acc = {}
    for r, g, b in px:
        key = (r // step, g // step, b // step)
        buckets[key] += 1
        s = acc.setdefault(key, [0, 0, 0])
        s[0] += r
        s[1] += g
        s[2] += b
    out = []
    total = len(px)
    for key, count in buckets.most_common():
        r, g, b = acc[key]
        out.append({
            "hex": "#{:02X}{:02X}{:02X}".format(r // count, g // count, b // count),
            "share": round(count / total * 100, 1),
            "rgb": [r // count, g // count, b // count],
        })
    return out


def luminance_profile(img):
    small = img.convert("L").resize((160, 160))
    px = list(small.getdata())
    dark = sum(1 for v in px if v < 60)
    mid = sum(1 for v in px if 60 <= v < 200)
    light = sum(1 for v in px if v >= 200)
    n = len(px)
    return {
        "dark_pct": round(dark / n * 100, 1),
        "mid_pct": round(mid / n * 100, 1),
        "light_pct": round(light / n * 100, 1),
        "mean": round(sum(px) / n, 1),
    }


def subject_box(img):
    """粗估主体外接框：与画面四角背景色差异明显的像素范围。

    白底/纯色底可用；复杂场景下结果仅供参考，不可直接当占比结论。
    """
    small = img.convert("RGB").resize((120, 120))
    w, h = small.size
    px = small.load()
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    bg = [sum(c[i] for c in corners) // 4 for i in range(3)]
    xs, ys = [], []
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) > 60:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    bw = (max(xs) - min(xs) + 1) / w
    bh = (max(ys) - min(ys) + 1) / h
    return {
        "bg_hex": "#{:02X}{:02X}{:02X}".format(*bg),
        "height_pct": round(bh * 100, 1),
        "width_pct": round(bw * 100, 1),
        "area_pct": round(bw * bh * 100, 1),
        "left_pct": round(min(xs) / w * 100, 1),
        "top_pct": round(min(ys) / h * 100, 1),
        "note": "粗估，仅对纯色底可靠",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="参考图粗测：主色 / 明暗 / 主体框")
    ap.add_argument("--image", required=True)
    ap.add_argument("--colors", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        from PIL import Image
    except ImportError:
        die("缺少 Pillow，先运行：apk add py3-pillow")

    from pathlib import Path
    path = Path(args.image)
    if not path.is_file():
        die(f"图片不存在：{path}")

    try:
        with Image.open(path) as im:
            im.load()
            size = im.size
            colors = quantize(im, bins=4)[: max(1, args.colors)]
            lum = luminance_profile(im)
            box = subject_box(im)
    except Exception as exc:  # noqa: BLE001
        die(f"无法解码：{exc}")

    result = {
        "file": str(path),
        "size": list(size),
        "colors": colors,
        "luminance": lum,
        "subject_box": box,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"文件：{path.name}  {size[0]}×{size[1]}")
    print(f"\n主色簇（前 {len(colors)}）：")
    for c in colors:
        bar = "█" * max(1, round(c["share"] / 4))
        print(f"  {c['hex']}  {c['share']:>5.1f}%  {bar}")
    print(f"\n明暗分布：暗 {lum['dark_pct']}%｜中 {lum['mid_pct']}%｜亮 {lum['light_pct']}%｜均值 {lum['mean']}")
    if box:
        print(f"\n主体外接框（背景 {box['bg_hex']}）：高 {box['height_pct']}%｜宽 {box['width_pct']}%"
              f"｜面积 {box['area_pct']}%｜左起 {box['left_pct']}%｜顶起 {box['top_pct']}%")
        print(f"  {box['note']}")
    else:
        print("\n主体外接框：未检出（背景可能非纯色，或多个主体）")
    print("\n提示：白底图里背景色常占首位，真正的主色要取第二、第三簇；占比与 hex 最终以人眼确认。")


if __name__ == "__main__":
    main()
