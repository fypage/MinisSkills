---
name: image-generator
description: >
  Generate or edit images using OpenMinis built-in model-use with the user-configured image_output provider, especially 智画创 / WisArt gpt-image-2. Trigger whenever the user asks to “生图”, “画图”, “生成图片”, “文生图”, “改图”, “图生图”, “图片编辑”, “出一张图”, mentions WisArt, 智画创, gpt-image-2, or provides an image plus an edit instruction. The assistant calls the model directly, saves outputs to /var/minis/attachments, and displays the image with site/model/clarity/aspect/quality/elapsed/path metadata.
version: 0.1
compatibility: OpenMinis Android 0.18+; uses minis-model-use image_output. No environment variable or raw API key required when the provider/model is configured in the app.
---
# OpenMinis Image Generator

Generate or edit images through **OpenMinis `minis-model-use`**. The user only adds/enables an image model in OpenMinis settings; the assistant calls it directly. Do not ask for `WISART_API_KEY` or raw provider credentials.

## Quick Workflow

1. Check available image models with `minis-model-use list --modality image_output` when unsure.
2. Decide mode: text-to-image (`generate`) or image-to-image/edit (`edit`).
3. Refine short user requests into a concrete visual prompt.
4. Run `/var/minis/skills/image-generator/scripts/openminis_image.py`.
5. Display the result inline with the metadata format below.
6. If model-use times out but WisArt backend created the job, recover from the logged-in WisArt frontend jobs API.

## Script Usage

Text-to-image:

```bash
python3 /var/minis/skills/image-generator/scripts/openminis_image.py generate \
  --prompt "未来城市日落，电影感，宽幅构图" \
  --size 16:9 --resolution 1K --quality auto --n 1
```

Image-to-image / edit:

```bash
python3 /var/minis/skills/image-generator/scripts/openminis_image.py edit \
  --image /var/minis/attachments/input.png \
  --prompt "保留人物身份和构图，改成赛博朋克雨夜风格" \
  --size 9:16 --resolution 1K --quality auto --n 1
```

For image-to-image, the wrapper compresses local reference images, converts them to data URI, and passes them as top-level `images: [data_uri]` through the normal generations channel. This is the format verified with WisArt through `minis-model-use`. Do not upload reference images to a VPS/public host.

## Parameters

| Parameter | Default | Notes |
|---|---:|---|
| `provider` | auto, prefer `智画创` | Uses the configured OpenMinis provider. |
| `model` | auto, prefer `gpt-image-2` | Uses first available image_output model if preferred one is absent. |
| `size` | `1200x675` | WisArt also accepts aspect ratios: `1:1`, `4:5`, `3:4`, `2:3`, `3:2`, `4:3`, `16:9`, `9:16`, `21:9`. |
| `resolution` | `1K` | WisArt frontend clarity tier: `1K`, `2K`, `4K`. |
| `quality` | `auto` | Compatibility field. Prefer `resolution` for clarity; use `medium`/`high` only when needed. |
| `n` | `1` | Generate one first unless the user asks for more. |
| `response_format` | `url` | Reduces large base64 timeout risk. |

## Output Format

After every successful generation, display exactly this style:

```md
![生成图片]({minis_url})

### 生图信息

站点：`{site}`  
模型：`{model}`  
清晰度：`{pixel_size}`  
比例：`{aspect}`  
质量：`quality={quality}`  
耗时：`{elapsed}`  
文件路径：`{path}`
```

Rules:
- `清晰度` is the actual output pixel dimensions read from the saved file, e.g. `941x1672` or `1672x941`.
- `比例` is the actual/fallback aspect ratio, e.g. `9:16`, `16:9`, `1:1`.
- Do not show a separate `张数` line by default.
- Do not show a separate `1K/2K/4K` line by default; it is only an internal/request tier.
- Do not add a copy block unless the user asks.

## WisArt Timeout Recovery

WisArt's OpenAI-compatible `/v1/images/generations` is synchronous and may time out while the backend job still succeeds. If `minis-model-use` returns errors such as `stream was reset: CANCEL`, `HTTP 502`, or `Client.Timeout or context cancellation while reading body`:

1. Do not blindly retry multiple times.
2. If logged into WisArt in the browser, open/query:
   - `https://wisart.kuaileshifu.com/api/jobs?limit=8`
3. Find the latest `status: success` job matching the prompt/model/size.
4. Download its first output path, e.g. `https://wisart.kuaileshifu.com/outputs/jobs/.../01.png`.
5. Copy the downloaded file to `/var/minis/attachments/` and display it with the normal metadata card.

Useful WisArt frontend APIs:

```txt
GET /api/image-models   # model list, supported 1K/2K/4K, point costs
GET /api/meta/enums     # job/failure/reference-mode enums
GET /api/jobs?limit=8   # recent jobs and output paths
```

## Prompt Guidance

- Prefer one strong prompt over repeated retries.
- For edits: explicitly say what to keep and what to change.
- For portraits: preserve identity, pose, clothing, facial structure, and gaze unless the user asks otherwise.
- For product/logo/text images: specify exact text, layout, background, and color palette.
- For UI/poster prompts: request clean typography, controlled hierarchy, and avoid unwanted phone/app screenshot artifacts when not desired.

## Failure Handling

- If no image_output model is available, ask the user to add/enable a生图模型 in `[Settings → Providers](minis://settings/providers)` or `[Settings → Model Groups](minis://settings/model-groups)`.
- If output path is relative, retry with an absolute `/var/minis/attachments/...` path.
- If WisArt backend shows success but local fetch timed out, recover from `/api/jobs` as above.
- If the provider reports maintenance/unavailable, stop retrying and report it briefly.
