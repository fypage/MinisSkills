# WisArt / 智画创 Historical Recovery Notes

> **历史资料，2026-07-17 归档：**当时曾出现服务关闭公告，并据此记录任务恢复方法。此文件不判断当前可用性；是否可提交新任务必须以 `minis-model-use list --modality image_output` 的运行时结果和用户选择为准。

该历史路径使用 OpenMinis `minis-model-use`；供应商已在 App 中配置时无需读取原始 API Key。

## Historical OpenMinis model-use formats (archived examples, not current wrapper inputs)

Text-to-image request body:

```json
{
  "model": "gpt-image-2",
  "prompt": "A cinematic product poster",
  "size": "16:9",
  "resolution": "1K",
  "quality": "auto",
  "n": 1,
  "response_format": "url"
}
```

Image-to-image/edit request body verified with WisArt through model-use:

```json
{
  "model": "gpt-image-2",
  "prompt": "keep identity, change style",
  "images": ["data:image/jpeg;base64,..."],
  "size": "9:16",
  "resolution": "1K",
  "quality": "auto",
  "n": 1,
  "response_format": "url"
}
```

Use top-level `images: [data_uri]` for model-use. Do not default to `/images/edits` for this path.

## Historical API boundaries (archived 2026-07-17)

以下是归档时的供应商口径，不是当前服务承诺，也不是 v1.2.1 包装器的输入契约。上方请求示例仅保留历史恢复语境；当前 OpenAI 包装器只接受 `auto` 或正整数 `WxH`，不接受 `9:16` 等比例字符串，`resolution` 走经核对的扩展字段。不得直接照抄历史请求发起新任务。运行时模型列表只能证明路由已配置，不能证明远端在线或参数受支持。

- `/v1/images/generations`: `n=1–5`; `response_format=url|b64_json`; maintenance returns HTTP 503.
- `/v1/images/edits`: multipart `image` may repeat, or JSON may use `images`; supports at most 16 JPG/JPEG/PNG/WebP/GIF references.
- `size`: accepts `auto`, common aspect ratios, `宽x高`, or `宽*高`; backend maps arbitrary dimensions to the closest aspect and infers 1K/2K/4K by area.
- `quality`: `auto|low|medium|high|hd`; with ratio/auto size, medium maps to 2K and high/hd to 4K.
- `mask`, `background`, `moderation`, `output_format`, `output_compression`, and `user` are accepted for compatibility but may be ignored by the active generation channel.

## WisArt frontend APIs for recovery

When synchronous OpenAI-compatible generation times out but the backend job succeeds, recover through the logged-in frontend APIs:

```txt
GET /api/image-models
GET /api/meta/enums
GET /api/jobs?limit=8
GET /outputs/jobs/YYYYMMDD/job_xxx/01.png
```

`/api/image-models` returns supported models and resolution tiers, e.g. `nano-banana-2`, `nano-banana-pro`, `nano-banana-2-lite`, `agnes-image-2.1-flash`, `gpt-image-2`, each supporting `1K/2K/4K` with point costs.

`/api/jobs` returns fields used for display/recovery:

```json
{
  "status": "success",
  "model": "gpt-image-2",
  "size": "16:9",
  "resolution": "1K",
  "n": 1,
  "outputs": ["outputs/jobs/20260710/job_xxx/01.png"],
  "created_at": 1783697776,
  "started_at": 1783697777,
  "finished_at": 1783697813
}
```

Common timeout/failure fields:

```json
{
  "failure_category": "image_timeout",
  "progress_stage": "error_image_timeout",
  "progress_message": "net/http: request canceled (Client.Timeout or context cancellation while reading body)",
  "points_refunded": true
}
```

Recovery matching must use `created_at >= request_started_at` and exact `prompt/model/size/resolution/n`. Accept only `status="success"` with non-empty `outputs`; download every output path. Real 4K failures can have `status="failed"`, `outputs=[]`, and non-empty `ai_upscale_sources` because the base generation succeeded but all AI upscalers failed. Do not silently treat an upscale source as the requested final image. Check `points_refunded` before stating whether points were returned.

## Display metadata

Prefer actual saved image dimensions over requested resolution tier:

```md
站点：`智画创`
模型：`gpt-image-2`
清晰度：`941x1672`
比例：`941:1672`（精确）；约 `9:16`（近似，不能作为严格画幅验收）
质量：`quality=auto`
耗时：`38s`
文件路径：`/var/minis/attachments/xxx.png`
```
