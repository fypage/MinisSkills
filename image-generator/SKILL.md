---
name: image-generator
description: 通过用户在 OpenMinis 中配置的 image_output 模型生成或编辑图片；适用于生图、画图、文生图、图生图、改图、局部修改、海报、Logo、产品图、角色图、风格迁移和多参考图编辑；支持异步任务通道（提交拿 task_id、按 id 查询/列表/取消、Idempotency-Key 幂等重试，可经 App 供应商转发而无需明文 Key）。自动核对可用模型，本地处理参考图，将结果保存到 /var/minis/attachments，验证真实图片与尺寸，并以内联媒体和可核实元数据交付。
version: 1.4.0
compatibility: OpenMinis Android 0.18+；主通道 minis-model-use image_output，凭据留在 App 供应商设置中；异步通道优先经供应商转发（脚本不接触明文 Key），直连时才用 `$LUPI_API_KEY` 或 `/var/minis/shared/image-gen/lupi-api-key.txt`（0600）；grok2api 走 `$GROK2API_KEY` 或 `/var/minis/shared/grok2api/admin.txt` 的 CLIENT_KEY 行。一律不外显。
---

# OpenMinis 图像生成与编辑

## 核心原则

1. 主通道通过 `minis-model-use` 调用用户已配置的 `image_output` 模型；不索取或输出 API Key。异步直连通道只能读取用户已提供的凭据环境变量或 shared 凭据文件，绝不在文档、日志、交付中回显。
2. 实际生图前动态查询模型，不把临时供应商状态当作长期事实。
3. 用户指定模型/供应商时不擅自替换；未指定时才自动选择可用路由。
4. 参考图在本机预处理，以 data URI 随请求发送给所选模型供应商；未经明确同意不上传公共临时图床。
5. 默认先生成 1 张；多张独立计费（噜皮生图 1 张 = 10 积分），用户明确要求后再增加。
6. 超时、502、524、连接重置属于结果不确定，不自动重试或切换付费供应商。
7. 只有成功保存并解码的真实图片才能交付；模型文字响应或改写后的提示词不算图片。
8. 提交后以 `task_id` / `Idempotency-Key` 为凭据续查，不以"等太久"判定失败；重试复用同一幂等键，不另起新任务。
9. `results[].width/height` 与本地解码是唯一的像素事实；供应商的 `size` 请求值可能被上游改写（噜皮实测 1024x1024 → 1254x1254）。
10. **交付必附六行生图信息**（站点／模型／清晰度／比例／耗时／文件），写成普通段落、值套行内代码、`文件` 给可点链接——不进代码围栏。不得压成单行概括，不得省略任一行，`文件` 不得写“约 2.35 MB”这类估算，须给格式与精确字节数。缺此六行即视为交付不完整。

## 按需参考

- 供应商协议、特殊路由和费用失败边界：`references/provider-compat.md`
- 噜皮生图异步任务通道（提交 202 / 按 task_id 查询 / `Idempotency-Key` / 直链 UA 与签名时效）：`references/lupi-async-api.md`
- grok2api 图片通道（同步、模型与比例白名单、实测像素档、公开媒体 URL、编辑仅 JSON）：`references/grok2api-image.md`
- 提示词编排、编辑保留项、文字/Logo、巨物题材：`references/prompt-recipes.md`
- 历史智画创任务恢复：`references/wisart-api.md`（仅历史资料，不代表当前状态）
- GRSAI 未并入后端审计：`references/grsai-option-audit.md`

## 标准工作流

### 1. 理解请求

确定模式：

- `generate`：纯文本生成；
- `edit`：一张或多张参考图的编辑/图生图。

保留用户明确给出的身份、人数、姿态、构图、文字、画幅、风格和数量。短提示可在不改变意图的前提下补全；完整提示原样提交。缺失信息只有会显著改变结果或费用时才询问。

### 2. 查询并选择模型

```sh
minis-model-use list --modality image_output
```

也可使用包装器：

```sh
python3 /var/minis/skills/image-generator/scripts/openminis_image.py --list-models
```

选择规则：

1. 用户明确指定的当前已配置路由；
2. 未指定时优先精确匹配 `gpt-image-2`，否则选当前列表首项；
3. 特殊适配只决定请求格式，不代表服务在线或价格更优。模型列表只证明已配置，不能代替远端验证。

同一模型名出现在多个供应商时必须用供应商标签消歧。无可用模型时停止，并引导至 [供应商设置](minis://settings/providers) 或 [模型组](minis://settings/model-groups)。

### 3. 执行

依赖 `python3`、Pillow 和 `minis-model-use`；缺少 Pillow 时先安装 `apk add py3-pillow`，不得降级为仅检查文件头。先核对所选供应商支持的尺寸/质量；配置声明 `image_output` 不等于所有编辑参数均兼容。

文生图：

```sh
python3 /var/minis/skills/image-generator/scripts/openminis_image.py generate \
  --prompt "未来城市日落，电影感，宽幅构图" \
  --size 1536x1024 --quality auto --n 1
```

图生图：

```sh
python3 /var/minis/skills/image-generator/scripts/openminis_image.py edit \
  --image /var/minis/attachments/input.png \
  --prompt "仅改变环境为赛博朋克雨夜；保留人物身份、姿态和构图不变" \
  --size 1024x1536 --quality auto --n 1
```

多参考图重复传入 `--image`，最多 16 张。默认将最长边压到 1024px、无透明图转 JPEG quality 85；透明图保留 PNG。只有确需原图分辨率时用 `--ref-max-side 0`。

常用参数：

| 参数 | 默认 | 说明 |
|---|---:|---|
| `--provider` | 自动 | 指定供应商标签；建议与 `--model` 一起使用 |
| `--model` | 自动 | 在当前可用路由中优先 `gpt-image-2`，否则选列表首项；不偏向固定供应商 |
| `--size` | `1200x675` | OpenAI 用像素尺寸或 auto，不接受比例字符串；Gemini 支持限定比例，像素值转比例并警告；见适配文档 |
| `--quality` | `auto` | 供应商语义可能不同 |
| `--resolution` | 省略 | 仅明确支持时传 `1K/2K/4K` |
| `--n` | `1` | OpenAI 1–5，Gemini 1–4，picpi 仅1；多图可能增加费用 |
| `--timeout` | `900` | 超时结果不确定，不自动重试 |
| `--output` | 自动 | 必须是 `/var/minis/attachments/` 下尚不存在的文件路径，不覆盖已有文件 |

`--extra-body` 仅用于已核对文档的非核心扩展字段；不得借此覆盖模型、数量、提示词、参考图或请求路由。对不支持的参数停止或明确提示，不得把忽略的参数声称为已生效。

### 3b. 异步通道（长耗时 / 断线续查 / 并发）

当供应商支持异步任务（当前：噜皮生图 `image.mlgb7.com`），或用户明确要求"提交后拿 task_id、稍后取结果"时，走 HTTP 异步通道，脚本：

```sh
# 首选：经 App 已配置的供应商转发（无需明文 Key；见下方第 8 条）
python3 /var/minis/skills/image-generator/scripts/lupi_async.py --transport provider submit \
  --prompt "一张极简产品海报" --size 1024x1024 --n 1

# 提交（直连；默认生成新 Idempotency-Key）——仅在确已配置 $LUPI_API_KEY 时使用
python3 /var/minis/skills/image-generator/scripts/lupi_async.py submit \
  --mode generate --prompt "一张极简产品海报" --size 1024x1024 --n 1

# 编辑（multipart，本地参考图；multipart 只走直连）
python3 /var/minis/skills/image-generator/scripts/lupi_async.py submit \
  --mode edit --image /var/minis/attachments/ref.png --prompt "改成未来城市夜景"

# 按 task_id 查询（支持逗号分隔多个）/ 列最近任务 / 取消
python3 /var/minis/skills/image-generator/scripts/lupi_async.py poll --ids api_gen_xxx,api_edit_yyy
python3 /var/minis/skills/image-generator/scripts/lupi_async.py list --limit 10
python3 /var/minis/skills/image-generator/scripts/lupi_async.py cancel --id api_gen_xxx

# 等终态并落盘（5s 起、×1.5 递增、封顶 20s；超时标 ambiguous，不重发；多图自动编号）
python3 /var/minis/skills/image-generator/scripts/lupi_async.py wait \
  --id api_gen_xxx --timeout 600 --download --output poster.png
```

> 落盘规则：多图自动编号；目标已存在时自动加 `-1`/`-2` 后缀，**既不覆盖也不报错**。返回 `ambiguous: true` 表示超时未定，先 `poll` 再决定，不要重发。

纪律：

1. 提交后**必须**拿到 `task_id`（与 `id` 同值）与 `poll_url`；只拿到 HTTP 202 不算有结果。
2. 网络超时/连接重置后的重试：**复用原 `Idempotency-Key`**（同值实测返回同一 task_id），换新任务才换新 key。不要用新 key 重发一次，那等于再买一张。
3. 终态判 `terminal:true` 或 `status ∈ {success, failed, error, cancelled}`；`failed` 也是终态，要报 `error_code`/`public_error`，不是继续等。
4. 拿到 `results[].url` 立即下载：直链带 `expires`（实测为生成次日 UTC 00:00）且拒 `Python-urllib` 默认 UA（403）。`lupi_async.py` 已按 `curl/8.5.0` 取图并 Pillow 解码验证。
5. ★**该站的普通（同步）调用会静默丢图**：`minis-model-use run` 以图片风格参数调用时，上游实际在后台跑成了任务（18:11 那次 `success` 40s、出图 1 张），但 App 侧 48–96s 后只把 prompt 文本当结果返回、不留图片文件。故对噜皮一律走 `--transport provider` 或直连异步，**不要用同步通道出图后宣称"已生成"**（无本地文件即视为未交付）。
6. 异步与直连同源同价同上游，异步不是"更省"，只是把等待搬到轮询；单张结果仍 30–60s。
7. 计费：该站**一次生成 10 积分**、并发上限 4；重发一单就是再花 10 积分，故幂等复用不是可选优化。同步通道丢图那两次，服务端其实已出图并计费。
8. 凭据优先级：**provider 传输**（App 供应商设置里的 Key，脚本根本不接触明文）＞ `$LUPI_API_KEY` ＞ `/var/minis/shared/image-gen/lupi-api-key.txt`（0600）。文档、日志、交付里一律不回显；直链里的 `owner`/`signature` 同样当敏感值截断。

端点、响应字段、状态机与未验证项见 `references/lupi-async-api.md`。

### 3c. Grok Imagine（grok2api，同步通道）

自建 `https://grok.a18016.ccwu.cc`，**同步返回**，没有 task_id：

```sh
python3 scripts/grok_image.py models
python3 scripts/grok_image.py gen --prompt "…" --model grok-imagine-image-2.0 --ratio 2:3 --n 1 --json
python3 scripts/grok_image.py edit --prompt "…" --image-url https://…/v1/media/images/img_xxx --json
```

1. **先看 `/readyz` 的具体 component**：`grok_web` 带 Statsig 预热提示仍可用；`grok_console` 显示「无可用账号」时该 scope 模型不可用。`state: degraded` 本身不代表坏。
2. 请求只收 JSON（multipart 415）；`aspect_ratio` 有白名单，`quality` 仅 `low|medium`，`resolution` 仅 `1k|2k`（Web 生成路径实测 `2k` **不改变尺寸**）。
3. 实测像素：`1:1→960×960`、`3:2→1152×768`、`2:3→768×1152`（请求 `1024x1536` 会被缩到 `768×1152`）、`9:16→720×1280`。**lite 忽略比例**，只会出 `832×1248`，换来 3 秒出图。
4. 编辑端点仅 JSON、`image.url` 必须是**公网可读**地址（`file_id` 不支持）；可直接用上一次生成的媒体 URL 回灌，实测可行；Web 编辑限 `n=1`。
5. **媒体 URL 不带 key 也能打开**（实测 `noauth=200`）——拿到链接即可看图。交付前先下载到本地再内嵌，别把媒体 URL 贴到公开场合。
6. 同步失败没有幂等键：超时/断流等于结果不确定，重发就是新任务，不自动重试。

### 4. 验证

包装器应完成：

- 仅交付本次调用产生、位于附件目录且未覆盖既有文件的输出；
- 文件非空，Pillow 完整解码；拒绝截断图、伪文件头和 HTML/JSON 错误文本；
- 逐张读取实际像素尺寸与比例，区分请求张数和已验证张数；少图不补任务；
- 媒体链接保留子目录并百分号编码；
- 在正常返回、超时、启动异常时清理临时请求；编辑结束清理本次压缩副本，不删除原始参考图；
- 日志只存必要状态、提示词哈希和脱敏诊断，不原样打印或保存供应商响应；每任务使用独立日志；
- 提交后超时、网关故障或无法证明未执行的失败标记为 ambiguous，不自动重试；即使本地已有图片也不能据此断言远端任务终态或计费。
- 敏感请求清理与生成结果保留分离：异常时保留本次结果和可恢复路径，不因报错销毁已生成图片；正式附件须完整写入后原子无覆盖发布。
- SIGTERM 受控清理不代表远端取消；SIGKILL、系统强杀、崩溃无法保证清理，不能仅凭 submitted 日志判定供应商未完成。历史遗留文件需先核实归属与活跃性，不自动删除。

对文字、Logo、人物身份、手部或精细编辑，交付前用 `read_image` 视觉核验。不能仅凭模型返回成功就声称文字准确或身份完全一致。

### 5. 恢复已生成媒体

若模型已成功返回 `minis://attachments/...`，但 Linux 路径暂不可读，可恢复同一份媒体：

```sh
python3 /var/minis/skills/image-generator/scripts/browser_recover.py \
  --url minis://attachments/example.png \
  --output /var/minis/attachments/example-recovered.png
```

这是从原媒体画面恢复，不是重新生图；不得再次调用模型。Canvas 会重编码为 PNG，不保证原始字节、元数据、动画或色彩信息保留。只接受附件资源 URL，输出不覆盖已有文件；必须取得专用标签 ID 才能操作，绝不回退到默认标签。恢复失败时保留原始媒体 URL，并如实说明路径不可读。

## 失败处理

- 本地参数、文件不存在、MIME 不支持、路径越界：修正后可重试，因为尚未提交模型任务。
- 明确的模型不存在、参数拒绝：停止；不自动换付费供应商。只有提交前错误或可靠终态证据才能确认未执行。
- 提交后不明错误但已拿到 `task_id`：先用该 id 续查（`lupi_async.py poll`），有终态就按终态交付；无终态才标不确定。
- 502/503/524/读取超时/连接重置及其他提交后不明错误：报告“结果不确定”，附任务日志；不自动重试。异步通道的下一次重试必须复用原 `Idempotency-Key`，不得换新 key 再发一单。
- 输出不是图片或无法解码：拒绝交付，不把错误文件改扩展名冒充图片。
- 多图只返回一张：只交付实际得到的图片，说明与请求数量差异，不擅自补发任务。

## 输出格式

> **铁律**：图必有条。任何产图回复都要以六行生图信息收尾——**普通段落，不进代码围栏**，值用行内代码，`文件` 一行给可点链接。缺行、压成一行、或只有文字约数（如“约 2.35 MB”），都算交付未完成。

每张图片以内联方式显示：

```md
![生成图片]({minis_url})
```

随后给出（**照此排列，写成普通段落**——值套行内代码呈高亮，`文件` 用链接；不要塞进代码围栏，那样会变成一整块黑底代码，不便阅读）：

**生图信息**

站点：`{provider}`
模型：`{model}`
清晰度：`{actual_width}×{actual_height}`
比例：`{actual_aspect}`
耗时：`{elapsed}`
文件：[{format} 原图]({minis_url})｜`{bytes}` 字节

排列固定为以上六行：`站点` 写上游品牌（与供应商标签不同时，括号补注供应商）；`清晰度` 用全角 `×` 连接，不写 `x`；`比例` 写约分后的 `W:H`；`耗时` 用中文单位（如 `51 秒`）；`文件` 写格式与字节数，须与落盘文件一致。`质量` 默认不出，仅在有返回证据时追加一行。块外另给一行可点的文件链接（`文件：[原图 PNG](minis://...)`），便于直接打开或保存。

`质量` 为请求参数，不代表已验证供应商实际生效；只有明确的返回证据才可补充实际质量。`清晰度` 与 `比例` 必须来自实际文件；精确约分比例与近似常见比例分别标注（近似值写“约”），不以容差标签充当严格画幅验收。未能读取时明确写请求值，不伪装成实际值。默认不展示完整提示词、请求 JSON、任务日志或额外“张数/1K”行，除非用户要求。

## 维护门禁

修改脚本后执行：

```sh
cd /var/minis/skills/image-generator
BROWSER_RECOVER_LIVE_TEST=0 python3 -m unittest discover -s scripts -p 'test_*.py' -v
python3 -m py_compile scripts/openminis_image.py scripts/browser_recover.py scripts/lupi_async.py
```

测试不得实际发起付费生图；模型调用一律 mock。浏览器真机探针须另行显式启用，不能混称为离线测试。

评估规则与人工工具轨迹验收见 `evals/acceptance.md`。`evals/evals.json` 的字符串检查至多验证输出措辞，不能证明发生了工具调用、没有重试、没有上传或已视觉核验；不得将字符串命中或版本升级称为修复通过。发布结论须分别记录离线测试、人工轨迹与远端验证的通过/失败/未验收状态。上述“应完成”是验收要求，不是未经测试的成功保证。
