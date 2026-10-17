# grok2api 图片通道（实测记录，2026-10-17）

> 对象：自建 `chenyme/grok2api` v3.1.6（`ghcr.io/chenyme/grok2api@sha256:7d679e3e…`），部署于洛杉矶 `45.207.207.75`，公网 `https://grok.a18016.ccwu.cc`。
> 下列参数、尺寸、耗时均为**真机实测**，不是照抄文档。源码读自 `/tmp/gk`（v3.1.6 tag 解包）。

## 1. 接入前先看 `/readyz`

```bash
curl -s https://grok.a18016.ccwu.cc/readyz
```

- `grok_web` = `degraded` + 「Statsig 尚未完成预热」→ **可用**，请求时按需重试。
- `grok_console` = `unavailable` + 「当前没有可用于已启用路由的账号」→ 该 scope 的模型不可用。
- `state: degraded` 不等于坏，**只看具体 component**；图片只要 `grok_web` 有账号即可跑。

## 2. 鉴权与模型

- 头：`Authorization: Bearer g2a_…`（管理后台生成的 client key，非 admin 会话 cookie）。
- `GET /v1/models` 实际返回 8 条（2026-10-17）：`grok-4.7`、`grok-composer-2.5-fast`、`grok-chat-fast`、`grok-imagine-image`、`grok-imagine-image-2.0`、`grok-imagine-image-edit`、`grok-imagine-image-lite`、`grok-imagine-video`。

| 模型 | 能力 | 实测表现 |
| --- | --- | --- |
| `grok-imagine-image-2.0` | 生成 | 11–18s，比例受控，质量最好 |
| `grok-imagine-image` | 生成（quality 变体） | 同协议 |
| `grok-imagine-image-lite` | 生成（fast） | **2.9s**，但**忽略 aspect_ratio**，只会出 2:3 竖图 |
| `grok-imagine-image-edit` | 编辑 | 3.1s，需公网可读的图像 URL |

## 3. 生成端点

```
POST /v1/images/generations
Content-Type: application/json      ← 仅 JSON，multipart 直接 415「图片生成仅支持 application/json」
```

请求字段（Go handler `imageGenerationRequest`）：`model`、`prompt`、`n`（1–10）、`size`、`aspect_ratio`、`resolution`、`quality`、`response_format`、`stream`、`partial_images`。

- `aspect_ratio` 白名单：`auto 1:1 16:9 9:16 4:3 3:4 3:2 2:3 2:1 1:2 19.5:9 9:19.5 20:9 9:20`；也给 `size` 别名（`1024x1536→2:3`、`1024x1024→1:1`、`1792x1024→3:2` 等）。**不在白名单即 400**。
- `quality` 仅 `low` / `medium`（空也行），其他值 400。
- `resolution` 仅 `1k` / `2k`；Web 生成路径实测 `2k` **不改变输出尺寸**，只对 Console 有意义（console 当前无账号）。
- `stream: true` 必须 `n=1`；`partial_images` 0–3 且须配合 `stream`。
- `response_format`: `url`（默认）或 `b64_json`。

响应：`200 {"created": <unix>, "data": [{"url"|"b64_json", "mime_type": "image/jpeg", "revised_prompt": ""}]}`，**同步返回，没有 task_id / 轮询**。

## 4. 实测尺寸档（请求值 ≠ 像素值）

| 请求 | 实际像素 | 说明 |
| --- | --- | --- |
| `1:1` | 960×960 | |
| `3:2`（或 `size=1792x1024`） | 1152×768 | |
| `2:3`（`size=1024x1536`） | 768×1152 | 请求 1024×1536 会被缩到 768×1152 |
| `9:16` | 720×1280 | |
| `9:16` + `resolution=2k` | 720×1280 | **2k 无效** |
| lite + `9:16` | 832×1248 | lite 忽略比例 |

→ 与噜皮一样：**像素只认本地解码结果**，不认请求参数。

## 5. 媒体 URL 是公开的（注意隐私）

返回的 `url` 形如 `https://grok.a18016.ccwu.cc/v1/media/images/img_<id>`，直连本地资产库（`/app/data/media`）。

- **不带 key 也能取到图**（实测 `noauth=200`）：拿到 URL 的任何人都能看图。
- 因此**别把媒体 URL 贴到公开场合**；交付时先下载到本地再内嵌。
- 图片以 **JPEG** 落库（`mime_type: image/jpeg`），本地归档不带 EXIF 隐私清理需求之外的处理。

## 6. 编辑端点

```
POST /v1/images/edits
Content-Type: application/json
{"model":"grok-imagine-image-edit","prompt":"…","images":[{"url":"https://…"}],"n":1}
```

- **只收 JSON**，不收 multipart（与 OpenAI 官方 edits 不同）。
- `image`/`images` 合计 1–8 张；`file_id` 明确不支持，只有 `url`。
- URL 必须**公网可读**——本地产物要先有公网地址才能编辑（可直接用上一次生成的媒体 URL 回灌，实测可行）。
- Web 编辑路径限 `n=1`，`resolution` 只能 `1k`。

## 7. 失败语义

- 同步请求，失败即失败（4xx/5xx + `{"error":{"message","type","code"}}`）。
- 网络层超时/中断 = **结果不确定**（服务端可能已生成并计配额），重发等于新任务，没有幂等键可用。
- `HTTP 503 upstream_unavailable` = 账号失效/冷却，去 `/readyz` 看 component。

## 8. 脚本用法

```bash
python3 scripts/grok_image.py models
python3 scripts/grok_image.py gen --prompt "…" --model grok-imagine-image-2.0 --ratio 2:3 --n 1 --json
python3 scripts/grok_image.py edit --prompt "…" --image-url https://…/v1/media/images/img_xxx --json
python3 scripts/grok_image.py get --url https://…/v1/media/images/img_xxx --out /var/minis/attachments/a.jpg
```

- Key 顺序：`$GROK2API_KEY` → `--key-file` → `/var/minis/shared/grok2api/admin.txt` 里的 `CLIENT_KEY` 行。
- 默认落 `/var/minis/attachments`，同名自动加 `-1`，落盘后读文件头核对像素与格式，不采信响应里的尺寸（响应根本不给尺寸）。
- `--json` 输出 `{http, elapsed_s, model, requested, mime, images[]}`，供拼六行生图信息。

## 9. 未验证 / 已知空缺

- 计费与配额窗口（grok2api 有 billing ledger，但没测额度上限）。
- `n>2`、`stream=true` 的 SSE 分片结构。
- Console 通道（`grok_console`）的 `resolution=2k`、`quality` 实际效果——当前无账号。
- 生成内容的实际审核尺度：**以线上实际拒绝为准**，此处不下结论。
