# grok2api 视频通道（实测）

> 站点 `https://grok.a18016.ccwu.cc`，grok2api v3.1.6，2026-10-17 实测。
> 鉴权同图片：`Authorization: Bearer g2a_…`（`$GROK2API_API_KEY` 或 `admin.txt` 的 CLIENT_KEY 行）。

## 一、接口与生命周期

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/v1/videos/generations` | 文生视频；返回 `{"request_id": "video_…"}` |
| POST | `/v1/videos/edits` | 视频编辑（需 Console 路由） |
| POST | `/v1/videos/extensions` | 视频延长（需 Console 路由） |
| GET | `/v1/videos/{request_id}` | 查状态 |
| GET | `/v1/media/videos/{asset_id}` | 取成品（MP4，**无需 key**） |

创建是**异步**：只回 `request_id`，随后轮询：

```json
{"request_id":"video_xxx","status":"done","model":"grok-imagine-video",
 "progress":100,"video":{"url":"https://…/v1/media/videos/vid_xxx","duration":6}}
```

状态取值 `pending|running|done|failed`；`_timeout` 是我方轮询超时，**不代表任务失败**，可用 `status`/`wait` 续查。

## 二、请求字段（严格，无兼容别名）

```json
{"model":"grok-imagine-video","prompt":"…","duration":8,
 "aspect_ratio":"16:9","resolution":"720p",
 "image":{"url":"https://…"}, "reference_images":[{"url":"https://…"}],
 "reference_audios":[{"voice_id":"…"}]}
```

- `duration` 1–15 秒，默认 8 —— **当前 web 路由不生效**，见下。
- `aspect_ratio` 白名单：`1:1 16:9 9:16 4:3 3:4 3:2 2:3`（无 21:9）。
- `resolution`：`480p 720p 1080p`。
- `image`（首帧）与 `reference_images`/`reference_audios` **互斥**；参考图模式必须带 `prompt`，`reference_images` 网关上限 8 张（Console 路由 7 张），每项 `url` 或 `file_id`，`url` 须公网可读。
- `reference_audios` 最多 3 个内置 `voice_id`；Console 未开通时上游 403。

## 三、实测像素与时长（当前账号池 = grok_web 路由）

| 请求 | 实际输出 |
|---|---|
| `16:9` + 720p | 1280×720 |
| `9:16` + 720p | 720×1280 |
| `1:1` + 720p | 720×720 |
| `4:3` + 720p | 960×720 |
| `duration` 8 / 10 / 15 | **恒 6.04 秒**（三个样本 `ffprobe` 全部 6.041667） |

★★ **web 路由实际只吃 720p**：

- `480p` → `503 upstream_model_unavailable`「当前账号池不支持该模型」——**文案误导，不是账号池问题**，可复现两次
- `1080p` → `400 unsupported_model`「视频编辑/延长仅支持路由到 Console grok-imagine-video: … 不支持 1080p」

★★ **图生视频（`image` / `reference_images`）在 web 路由不可用**：

```
400 unsupported_model: Grok Web 当前仅支持文本生视频；图片视频请使用 Build 或 Console Provider
```

要图生视频，得给 grok2api 加 Build/Console 账号并把 `grok-imagine-video` 路由指过去。

## 四、耗时与文件

- 生成 6.5–6.7 秒（720p、6 秒片），几乎没有排队。
- 文件 2.6–4.3 MB，H.264 + AAC，另含 mjpeg 封面流；无 key 也能取（实测 `206`）。
- 落盘 `/app/data/media/videos`（卷 `grok2api_grok2api-data`）。

## 五、脚本

```sh
python3 scripts/grok_video.py gen --prompt "…" --ratio 16:9 --resolution 720p --json
python3 scripts/grok_video.py gen --prompt "…" --no-wait          # 只建任务
python3 scripts/grok_video.py status --id video_xxx
python3 scripts/grok_video.py wait --id video_xxx --download
python3 scripts/grok_video.py edit   --prompt "…" --video-url https://…
python3 scripts/grok_video.py extend --prompt "…" --video-url https://…
```

- `gen` 默认等到 `done` 并下载到 `--out`（默认 `/var/minis/attachments`），文件名不覆盖。
- 下载校验 MP4 `ftyp` 头、`<10 KB` 直接判失败，避免把错误页存成视频。
- 轮询异常（网络抖动）不终止，继续下一轮；超时返回 `_timeout`。

## 六、未验证

- `edits` / `extensions` 的真实入参（`video.url` 是否必须公网、能否 `file_id`）——需 Console 账号才能实测
- 4:3 以外的 `3:2 / 2:3 / 3:4` 具体像素
- 并发上限、计费（grok2api 侧 32 条路由，当前 50 次请求 47 成功）
