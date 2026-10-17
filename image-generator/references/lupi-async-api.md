# 噜皮生图（image.mlgb7.com）异步任务通道

实测日期 **2026-10-17**，平台 `image.mlgb7.com`（nginx/1.24.0），实例标签 `噜皮生图`，
App 中 `provider_type=OpenAI`，模型 `gpt-image-2`、`gpt-image-2.5`（均声明 `image_output` + `image_input`）。

两条通道并存：

| 通道 | 入口 | 特征 |
|---|---|---|
| 同步 | `minis-model-use` / `scripts/openminis_image.py` | 一次调用等结果；**2026-10-17 晚复测会静默丢图**（见文末专节），不可作交付依据 |
| 异步 | 本文件的 HTTP 端点 / `scripts/lupi_async.py` | 提交即 202，按 task_id 查；可断线续查、可并发、可幂等重试 |

同步通道早期（`--provider 噜皮生图 --model gpt-image-2.5`）确曾生成成功、`verified: true`；但同日 18:0x 起两次复测（`gpt-image-2.5-flare` 96.6s、`gpt-image-2` 48s）都只回文本、无文件，而服务端任务其实 `success`。**以复测为准：该通道不可信，见文末「同步通道会静默丢图」。**
两者走同一上游，**异步通道不是"更便宜"，只是把等待搬到轮询**。

## 凭据

- **首选 `--transport provider`**：脚本不接触明文 Key，改由 App 里已配置的供应商（instance_label `噜皮生图`）发 passthrough 请求。`minis-model-use run --model '噜皮生图/gpt-image-2'` + `passthrough.endpoint` 会把路径替换到该供应商 base 之后，实测 `GET /v1/models` → 200、`POST /v1/images/generations` → 202，与直连等价。Key 只在 App 供应商设置里存在，不落盘、不进会话。
- 直连解析顺序：`--key-file` > `$LUPI_API_KEY` > `/var/minis/shared/image-gen/lupi-api-key.txt`（0600）。
- 形如 `lupi_<32 hex>`；无效/已吊销时 `401`，响应体：

```json
{"error":{"message":"密钥无效或已失效，请重新登录","type":"authentication_error","param":null,"code":"invalid_api_key"}}
```

- 文档/日志/报告只记路径与变量名，不回显值；直链里的 `owner`/`signature`/`expires` 一并按敏感处理。
- ★Key 一旦进入对话（含被压缩摘要带出），视为已泄漏：立即在平台重置，旧值 `401` 即为吊销成功。

## 端点清单

| 方法 | 路径 | 实测 |
|---|---|---|
| POST | `/v1/images/generations` | JSON，`async:true` → `202` |
| POST | `/v1/images/edits` | multipart，字段名 `image`；仅直连可用（provider 传输不支持 multipart） |
| GET | `/api/image-tasks?ids=a,b` | 200，逗号多 id |
| GET | `/api/image-tasks?limit=N` | 200，列最近任务（无 ids 时等同列表；`limit` 生效与否未逐一核，返回按时间倒序） |
| POST | `/api/image-tasks/<id>/cancel` | 200，body 须非空（`{}` 会被 provider 传输拒；直连可空）；对已终态任务返 200 但状态不变 |
| DELETE | `/api/image-tasks/<id>` | 405 |
| GET | `/api/image-tasks/<id>` | 200 但返回 SPA HTML —— **无路径式单 id 端点**，必须走 `?ids=` |

## 三个核心端点

### 1) 提交生成

```sh
curl https://image.mlgb7.com/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LUPI_API_KEY" \
  -H "Idempotency-Key: <可选，同任务复用同值>" \
  -d '{"model":"gpt-image-2.5","prompt":"一张极简产品海报","n":1,"size":"1024x1024","async":true,"response_format":"url"}'
```

`202`，约 1.2s 返回：

```json
{"object":"image_task","id":"api_gen_ff96…c38c","task_id":"api_gen_ff96…c38c",
 "status":"queued","poll_url":"https://image.mlgb7.com/api/image-tasks?ids=api_gen_ff96…c38c"}
```

`id` 与 `task_id` 同值。去掉 `async`／置 `false` 则走同步返回（本次未测，不猜测形态）。

### 2) 提交编辑（multipart）

```sh
curl https://image.mlgb7.com/v1/images/edits \
  -H "Authorization: Bearer $LUPI_API_KEY" -H "Idempotency-Key: <可选>" \
  -F "model=gpt-image-2.5" -F "prompt=改成未来城市夜景" \
  -F "n=1" -F "async=true" -F "response_format=url" \
  -F "image=@./reference.png"
```

同为 `202` + `api_edit_<…>` 前缀（实测 5.5s，含文件上传）。`n`、`size`、`quality`、`response_format=url` 与生成端点同义；
单图用 `-F image=@…`，多参考图应为重复同名字段（**未实测**，不写入流程保证）。

### 3) 查询任务

```sh
curl "https://image.mlgb7.com/api/image-tasks?ids=api_gen_xxx,api_edit_yyy" \
  -H "Authorization: Bearer $LUPI_API_KEY"
```

- 支持**逗号分隔多 id**（实测混查 gen+edit 正常），返回 `{"items":[…]}`，顺序与请求一致。
- 单条关键字段：`id` `status` `terminal` `mode`(generate/edit) `model` `size` `quality`
  `stage_code` `stage_label` `created_at` `updated_at`
  `requested_count` `succeeded_count` `failed_count` `cancelled_count` `pending_count`
  `duration_ms` `elapsed_ms` `error_code` `public_error` `results[]` `actions{resume_poll,cancel}`。
- `results[]`：`{"url","path","b64_json","revised_prompt","width","height"}`；`response_format=url` 时 `url` 有值、`b64_json` 为空串。

## 状态机（实测）

```
queued → running → success（terminal:true）
                ↘ failed / error（terminal:true，带 error_code + public_error）
```

`stage_label` 观测值：`等待上游首包`(`starting_generation`) → `上游生成中`(`generating`) → `接收图片` → `成功`。
判终态请用 `terminal` 布尔字段或 `status ∈ {success, failed, error, cancelled}`，**不要只看 `status=="success"` 就跳出**（失败也是终态，需要报错而不是继续轮询）。

## 幂等（实测成立）

同一 `Idempotency-Key` 重放 → **返回同一个 task_id**；第二次返回的是该任务的实时状态（实测由 `queued` 变为 `running`），不是新建任务。
- 网络超时/连接重置后的重试：复用原 key，不会重复扣费式重复生成。
- 换新任务必须换新 key。脚本默认每次生成 `bf-<uuid4>`，重试时显式传 `--idempotency-key`。
- 幂等作用域未测（同 key 换 prompt 是否报冲突、跨日是否失效）——不要假设，未知即未知。

## 结果直链的两条硬约束

1. **UA 门禁**：`url` 直链对 `Python-urllib/3.x` 默认 UA 返回 `403`；`curl/8.5.0` 与桌面 Chrome UA 均 `200`。
   脚本统一以 `curl/8.5.0` 取图（与 Legado 站点的反爬方向类似：**403 先怀疑 UA，不是 URL 失效**）。
2. **签名有效期**：`?expires=<unix秒>&owner=…&signature=…`，实测 `expires` = 生成次日 **UTC 00:00**（= 北京 08:00）。
   过期后链接不可取 → **拿到 results 就立即下载落盘**，不要留到下次会话再取。

## size 不保证生效

请求 `"size":"1024x1024"`，返回 `results[].width/height` 与实下载文件均为 **1254×1254**（PNG, RGB）。
即：`size` 是上游提示，实际像素以 `results[].width/height` 与本地解码为准。
交付时 `清晰度`/`比例` 必须写实测值，不得回填请求值。

## 计费与并发（平台口径，2026-10-17 用户账户截图）

- **一次生成 = 10 积分**（积分明细逐条 `-10`，描述"消耗 1 张图片积分"）；未实测 `n=2` 的扣费（推测按张计，不写入结论）。
- 因此"超时后用新 key 重发"不是无成本的：**每多发一单就是 10 积分**。这是幂等纪律的直接经济理由。
- **任务并发上限 4**（个人中心"任务并发 0/4"）：批量提交超过 4 个会排队或受限，脚本批量时自行限流。
- 新增账户初始 500 积分、每日签到 +139（当日为 1 天）。积分余额是用户侧事实，会在报告里被引用时以用户截图的当日数值为准，不写入长期结论。
- 用积分制意味着"失败是否退分"未知：失败任务按 `error_code` 报告，不声称已退分。

## 实测耗时（单张，n=1）

| 环节 | 观测 |
|---|---|
| 提交（JSON）返回 202 | 1.18s |
| 提交（multipart 编辑）返回 202 | 5.27–5.47s |
| 生成总耗时 `duration_ms` | 28.6s |
| 编辑总耗时 | 约 40–60s（4 次轮询节拍内完成） |
| 同步通道（minis-model-use）端到端 | 36.5s（早期成功一次；此后两次丢图） |
| 经 provider 传输提交 | 2.1–9.3s（每次起一个 `minis-model-use` 进程，开销随轮数累积） |

轮询节律建议：5s 起、×1.5 递增、封顶 20s（`lupi_async.py wait --interval 5`）。
单张 30–60s，`--timeout 600` 足够；不要用 30s 级超时判定失败。

## 模型白名单（服务端返回）

`codex-gpt-image-2`、`gpt-image-2`、`gpt-image-2.5`、`gpt-image-2.5-flare`、`gpt-image-2.5-sunburst`、`plus-codex-gpt-image-2`、`pro-codex-gpt-image-2`、`team-codex-gpt-image-2`

★ **非法 model 不会被 400 拒绝**：实测 `model: "not-a-model"` 仍返回 `202` 并建任务，随后状态是 `text_review`、`error_code=unsupported_model`、`succeeded_count=0`，`public_error` 里才列出白名单。故提交前先核对 `/v1/models`，别靠错因反查。

## ★同步通道会静默丢图（2026-10-17 实测）

`minis-model-use run`（provider `噜皮生图`，顶层 `prompt/n/size` 图片风格）：

| 次 | 模型 | App 侧返回 | 服务端实况 |
|---|---|---|---|
| 1 | gpt-image-2.5-flare | 96.6s 后只回 prompt 文本，无图片文件 | 后台任务成功出图 |
| 2 | gpt-image-2 | 48s 后同上 | `api_gen_f46aa398…` = `success` / 40.3s / `succeeded_count 1` |

即：上游把请求当异步任务跑，App 等不到就放弃，**结果留在平台、本地一无所有**，且两次都计费。
结论：对噜皮出图一律走 `--transport provider`（passthrough）或直连异步；用同步通道必须回头用 `list`/`poll` 核是否存在同名任务，**没有本地文件即视为未交付**。

## 失败态（实测）

- `status=failed` + `error_code=task_interrupted`：2026-10-17 一次提交在 `running` 169s 后中断，`succeeded_count=0`；同参数重发即成功。属上游偶发，**同 id 续查无意义**，重发即再计费一次。
- `status=text_review` + `error_code=unsupported_model`：model 不在白名单（见上节）。
- 脚本对失败返回 `{"ok": false, "terminal": true, "error_code": ...}`，不会重试——是否重发由人决定，并须提醒计费。

## 请求类型（易错）

- `async`、`n` 用**原生类型**（`true` / `1`），不要传字符串；multipart 编辑分支由 `_field()` 统一转 `true`/`1`。
- 字符串 `"true"` 在 JSON 端点也曾被接受，但不可依赖；布尔实测可稳定复现（2026-10-17 2/2 成功、1 次上游中断）。

## 输出里的敏感字段

脚本打印的 JSON 含结果签名直链（`owner`、`signature`、`expires`），可被任何人取图至过期。**不要把整段输出贴到公开处**；分享只发本地文件。

## 边界与未验证项

- 已验证（2026-10-17 补）：`GET /api/image-tasks?limit=N` 列表、`POST /api/image-tasks/<id>/cancel`、`DELETE` 405、路径式单 id 不存在、模型白名单、provider 传输等价性。
- **未验证**：`n>1` 的 `results` 多图结构、`b64_json` 模式、多参考图 edits、非 `auto` 的 `quality`/`size` 取值域、`limit`/分页参数是否真正生效。
- 计费口径未知，不声称"失败不计费"。失败任务只能据 `error_code`/`public_error` 报告。
- 提交后超时/连接重置 = 结果不确定：先按 `Idempotency-Key` 重放取回 task_id，再轮询；**不要另起新 key 重发**。
- 该平台是第三方中转站，凭据与政策随时可变；每次大任务前先跑一次 `poll` 或一次小尺寸试提交确认可用性。
