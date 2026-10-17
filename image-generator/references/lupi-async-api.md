# 噜皮生图（image.mlgb7.com）异步任务通道

实测日期 **2026-10-17**，平台 `image.mlgb7.com`（nginx/1.24.0），实例标签 `噜皮生图`，
App 中 `provider_type=OpenAI`，模型 `gpt-image-2`、`gpt-image-2.5`（均声明 `image_output` + `image_input`）。

两条通道并存：

| 通道 | 入口 | 特征 |
|---|---|---|
| 同步 | `minis-model-use` / `scripts/openminis_image.py` | 一次调用等结果，实测 35s；凭据留在 App 供应商设置 |
| 异步 | 本文件的 HTTP 端点 / `scripts/lupi_async.py` | 提交即 202，按 task_id 查；可断线续查、可并发、可幂等重试 |

同步通道已验证可用（`--provider 噜皮生图 --model gpt-image-2.5` 生成成功，`verified: true`）。
两者走同一上游，**异步通道不是"更便宜"，只是把等待搬到轮询**。

## 凭据

- 解析顺序：`--key-file` > `$LUPI_API_KEY` > `/var/minis/shared/image-gen/lupi-api-key.txt`（0600）。
- 形如 `lupi_<32 hex>`；无效时 `401`，响应体：

```json
{"error":{"message":"密钥无效或已失效，请重新登录","type":"authentication_error","param":null,"code":"invalid_api_key"}}
```

- 文档/日志/报告只记路径与变量名，不回显值。

## 三个端点

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

- **一次生成 = 10 积分**（积分明细逐条 `-10`，描述"消耗 1 张图片积分"）；`n=2` 应是 20 积分（未实测，按张计）。
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
| 同步通道（minis-model-use）端到端 | 36.5s |

轮询节律建议：5s 起、×1.5 递增、封顶 20s（`lupi_async.py wait --interval 5`）。
单张 30–60s，`--timeout 600` 足够；不要用 30s 级超时判定失败。

## 边界与未验证项

- **未验证**：取消任务的实际端点（`actions.cancel` 存在但接口未见）、历史任务列表、`n>1` 的 `results` 多图结构、`b64_json` 模式、多参考图 edits、非 `auto` 的 `quality`/`size` 取值域。
- 计费口径未知，不声称"失败不计费"。失败任务只能据 `error_code`/`public_error` 报告。
- 提交后超时/连接重置 = 结果不确定：先按 `Idempotency-Key` 重放取回 task_id，再轮询；**不要另起新 key 重发**。
- 该平台是第三方中转站，凭据与政策随时可变；每次大任务前先跑一次 `poll` 或一次小尺寸试提交确认可用性。
