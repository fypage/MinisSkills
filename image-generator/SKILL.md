---
name: image-generator
description: Generate, test, and refine images from user prompts. Use when the user asks to 生成图片, 画图, 测试提示词, 跑图, 做海报, 做封面, 壁纸, 插画, generate an image, create a picture, test an image prompt, or turn an idea into an image. Supports prompt optimization, model/provider fallback, image-output extraction, and local Pillow fallback.
version: 1.1.2
---
# Image Generator

## Boundaries

- Do the requested image task; do **not** create unrelated reusable API tools, environment-variable setup flows, or platform-agnostic CLIs unless the user explicitly asks.
- If the user says “参考这个提示词/工作流”, extract useful patterns and improve this skill/workflow; do not blindly implement the referenced artifact.
- Never print API keys, tokens, or environment variable values.

## Default workflow

1. If the prompt/theme is clear, generate immediately. Ask only when missing details block execution.
2. Prefer configured `image_output` models:
   - Run `minis-model-use list` and choose an available image-output model.
   - If duplicate model IDs exist, use `--provider <instance_label>` or the full entry id.
   - Default image model preference: try the provider that recently worked first; if it fails, try the next image-output provider.
3. Use common aspect-ratio defaults:
   - Portrait / 竖版 / 9:16: `1024x1792`.
   - Landscape / 横版 / 16:9: `1792x1024`.
   - Square / default: `1024x1024`.
4. Save final images under `/var/minis/attachments/` and embed inline with `![desc](minis://attachments/file.png)`.
5. After generation, report briefly: model/provider or fallback method, size, saved path, and one useful refinement suggestion.

## Model invocation pattern

Create a JSON input file in `/tmp` when `minis-model-use --input /var/minis/...` has path/offload issues.

OpenAI-compatible image call shape:

```json
{"prompt":"...","size":"1024x1792","quality":"hd","n":1}
```

Notes:

- Some providers return base64 inside Markdown data URLs, e.g. `![image](data:image/png;base64,...)`; extract and save to `/var/minis/attachments/`.
- If one provider fails with account/model support errors, do not retry it repeatedly; switch provider.
- If a provider times out once, one retry is reasonable; repeated timeouts should fall back or report clearly.
- If `quality:"hd"` times out with HTTP 524, retry once with `quality:"standard"` or provider-specific `quality:"auto"` before giving up.

## Provider notes

- `Token能量站/gpt-image-2` has worked for direct `minis-model-use` image generation. Use it as the first fallback when another OpenAI-compatible image provider fails.
- `picpi 皮皮工艺站/gpt-image-2` may fail with `Tool choice 'image_generation' not found in 'tools' parameter` or `The 'gpt-image-2' model is not supported when using Codex with a ChatGPT account.` This means the provider is routing generation through Codex `/responses` image tool or an unsupported ChatGPT/free account. Do not keep retrying; ask the user to switch the upstream channel/account to K12/Plus/Team or use another provider.
- WisArt (`https://wisart.kuaileshifu.com`) exposes OpenAI-compatible image endpoints:
  - `GET /v1/models`
  - `POST /v1/images/generations`
  - `POST /v1/images/edits`
  - Auth header: `Authorization: Bearer sk-...`
  - Generation body example: `{"model":"gpt-image-2","prompt":"...","size":"1200x675","quality":"auto","n":1,"response_format":"b64_json"}`.
  - Supported sizes include `auto`, ratios like `1:1`, `16:9`, `9:16`, and explicit dimensions like `1024x1024`, `1200x675`, `928x1664`; `quality` supports `auto`, `low`, `medium`, `high`, `hd`.
  - To add it to Minis, configure an OpenAI-compatible provider with custom base URL `https://wisart.kuaileshifu.com` and append `/v1` enabled, then use `gpt-image-2`.

## Prompt handling

Use the user's prompt as the source of truth. Do not rewrite the intent unless the user asks for prompt optimization or a technical change is required for the model call.

Convert vague requests into a concrete visual brief only when needed:

- Subject: main object/scene
- Style: photo, anime, ink painting, cyberpunk, minimalist poster, 3D icon, etc.
- Composition: close-up, wide shot, centered, rule of thirds, poster layout
- Color/mood: warm, dark, neon, pastel, cinematic, elegant
- Lighting/camera: softbox, window light, backlight, shallow depth of field, lens feel
- Text: include exact text only when user asks; keep text short

Portrait clarity rule:

- Prompts containing `soft-focus`, `dreamy`, `overexposed`, `beauty filter`, `shallow depth of field`, or `pastel` can produce overly blurry faces. If the user complains that the image is blurry, keep the mood but add: `sharp facial details, crisp eyes and eyelashes, clear hair strands, detailed accessories, sharp focus on face, avoid excessive blur`, and add negatives like `out of focus face, smeared details, over-smoothed skin, blurry artifacts`.

For long professional prompts, preserve structure but compress duplicates before sending to the model. Keep the visual hierarchy:

1. aspect ratio + medium/style
2. subject identity and age if relevant
3. pose/composition
4. face/skin/makeup/hair/clothing
5. scene/background
6. lighting/color/quality constraints
7. negative constraints such as “not juvenile, not westernized, not plastic skin”

Example expansion:

User: `生成一张猫咪图片`
Brief: `一只橘猫坐在窗台上，窗外雨夜霓虹，温暖室内灯光，电影感，柔和景深，1024x1024`.

## Local Pillow fallback

Use only when no working image-output model is available, or when the user asks for simple procedural graphics.

```sh
python3 /var/minis/skills/image-generator/scripts/procedural_image.py \
  --prompt "极光夜景，湖面倒影，山脉剪影" \
  --output /var/minis/attachments/aurora_night.png \
  --size 1024x1024
```

If Python/Pillow is missing:

```sh
apk add --no-cache python3 py3-pillow
```

When using this fallback, clearly say it is a local procedural image, not an AI image-model result.

## Output response style

Keep the response short:

```md
已生成：

![描述](minis://attachments/file.png)

方式：gpt-image-2 / Token能量站，1024x1792。  
下一版建议：加强妆容水光或降低背景复杂度。
```
