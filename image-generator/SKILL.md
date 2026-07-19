---
name: image-generator
description: >
  Generate or edit images through any user-configured OpenMinis image_output provider. Trigger for 生图、画图、文生图、图生图、改图、图片编辑、局部修改, or when an image plus editing instructions is provided. Select an active provider safely, keep references local, save outputs under /var/minis/attachments, validate real image dimensions, and return inline media with generation metadata.
version: 0.3
compatibility: OpenMinis Android 0.18+; uses minis-model-use image_output. No environment variable or raw API key required when the provider/model is configured in the app.
---
# OpenMinis Image Generator

Generate or edit images through **OpenMinis `minis-model-use`**. Credentials stay in provider settings; never ask the user to paste raw keys into chat.

## Provider status

- **智画创 / WisArt is active again as of 2026-07-18 and is the temporary preferred provider.** Its availability may be short-lived; verify it remains configured before use and do not blindly retry ambiguous failures.
- Prefer `智画创/gpt-image-2` when active, then another configured `image_output` provider. Never switch to a second paid provider after an ambiguous timeout unless the user explicitly asks; the first backend may still complete and charge.
- `picpi 皮皮工艺站/gpt-image-2` requires `messages + image_generation tool` for reliable output extraction. For text-to-image, send the prompt in `messages`; for image-to-image, send local compressed data URIs in the top-level `images` array plus the same tool request. Do not send it the wrapper's normal top-level `prompt/size/n` payload or Responses `input_image` objects; the backend may generate and bill an image while model-use receives only rewritten prompt text.
- If only retired providers are configured, stop and direct the user to [Providers](minis://settings/providers) or [Model Groups](minis://settings/model-groups).

## Quick Workflow

1. Run `minis-model-use list --modality image_output` when provider health or selection is uncertain.
2. Decide mode: text-to-image (`generate`) or image-to-image/edit (`edit`).
3. Refine short requests without overriding user-specified identity, composition, text, count, or aspect ratio.
4. Run `/var/minis/skills/image-generator/scripts/openminis_image.py` without a provider for safe auto-selection, or specify a known-active provider explicitly.
5. Validate every output as a non-empty decodable image under `/var/minis/attachments`; use actual pixel dimensions in metadata.
6. Display all returned images inline. On timeout, report ambiguity and inspect provider-specific job status only when such an API is documented and authenticated.

## Script Usage

Text-to-image:

```bash
python3 /var/minis/skills/image-generator/scripts/openminis_image.py generate \
  --prompt "未来城市日落，电影感，宽幅构图" \
  --size 16:9 --quality auto --n 1
```

Image-to-image / edit:

```bash
python3 /var/minis/skills/image-generator/scripts/openminis_image.py edit \
  --image /var/minis/attachments/input.png \
  --prompt "保留人物身份和构图，改成赛博朋克雨夜风格" \
  --size 9:16 --quality auto --n 1
```

For image-to-image, the wrapper converts up to 16 local references to data URIs and passes top-level `images: [data_uri]` through `minis-model-use`. It defaults to a 1024px longest side at JPEG quality 85; transparent images remain PNG. Use `--ref-max-side 0` only when original-resolution references are necessary and the larger payload is acceptable. Do not upload references to a VPS/public host.

## Parameters

| Parameter | Default | Notes |
|---|---:|---|
| `provider` | active provider, auto | Retired providers are excluded from automatic selection. |
| `model` | auto, prefer `gpt-image-2` | Uses the preferred model on an active provider, otherwise the first image_output model. |
| `size` | `1200x675` | Provider-dependent; common values include ratios such as `1:1`, `16:9`, `9:16` and pixel dimensions. |
| `resolution` | omitted | Optional provider-specific tier: `1K`, `2K`, `4K`; pass only when supported. |
| `quality` | `auto` | OpenAI-compatible field; semantics vary by provider. |
| `n` | `1` | Valid range `1–5`; generate one first unless the user asks for more. |
| `response_format` | `url` | Reduces large base64 timeout risk. |
| references | — | Edit accepts `1–16` JPG/JPEG/PNG/WebP/GIF files; animated GIF behavior is provider-dependent. |

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

## Timeout and failover policy

Treat `502`, `524`, connection reset, and read timeout as **ambiguous**, not definitive failure: a backend may still finish and charge.

1. Record provider, model, request start time, prompt hash, size, quality, count, and request file.
2. Do not blindly retry the same provider and do not automatically submit to another paid provider.
3. If the provider has a documented job API, match exact request fields and timestamp; accept only a successful terminal state with non-empty outputs.
4. If status cannot be queried, report the ambiguity and let the user choose whether to retry.
5. Retry automatically only for a definitive pre-submission/network failure known not to create a job, and at most once.
6. Never claim refund or success without provider evidence.

Historical WisArt recovery details are archived in `references/wisart-api.md`; they are not a route for new jobs.

## Prompt and execution guidance

- Prefer one strong prompt over repeated retries. Fill harmless placeholders only when the user delegates that choice.
- Preserve explicit character identity, count, composition, camera angle, aspect ratio, wardrobe, and text exactly; do not silently substitute characters.
- For edits, separate **must preserve** from **must change**. Keep references local as compressed data URIs by default.
- Never upload user references, masks, or private photos to public temporary hosting without explicit consent.
- For multiple requested images, use `n` only when the provider reliably returns independent outputs; otherwise submit sequentially and label each prompt, but warn about separate charges.
- For portraits, request natural anatomy, hands, eye direction, skin texture, and recognizable identity.
- For product/logo/text images, state exact text, spelling, layout, background, and palette; verify rendered text visually before claiming success.
- For UI/posters, request controlled hierarchy and exclude unwanted device-frame or screenshot artifacts.

## Failure Handling

- If no active image_output model is available, ask the user to add/enable one in [Providers](minis://settings/providers) or [Model Groups](minis://settings/model-groups).
- Output must resolve under `/var/minis/attachments/`; reject paths outside it.
- Validate `n=1–5`, edit reference count `1–16`, local file existence, MIME type, decodeability, output byte size, and actual dimensions.
- Treat HTTP `503` as unavailable and stop. Treat `502/524/timeout` as ambiguous under the policy above.
- If the returned file is HTML/JSON/error text renamed as an image, reject it.
- `mask`, `background`, `moderation`, `output_format`, `output_compression`, `resolution`, and `user` are provider-specific compatibility fields; do not promise effects without verification.
