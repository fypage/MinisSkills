# 生图通道适配

本文件把「电商视觉方法论」接到本机已有的生图能力上。**不引入第三方 CLI，不接触密钥。**

## 通道选择

| 通道 | 何时用 | 入口 |
|---|---|---|
| **A 噜皮生图（App 供应商）** | **默认**。`gpt-image-2`，2026-10-27 实测可用，62 秒出 `1254×1254` | `image-generator/scripts/openminis_image.py` |
| **B 噜皮异步** | 需要 task_id、断线续查、批量并发 | `image-generator/scripts/lupi_async.py` |
| **C orbitix** | 可用。`gpt-image-2.5-flare`，2026-10-27 实测出图正常（998 KB PNG） | 同上，`--model gpt-image-2.5-flare --provider orbitix` |
| **D grok2api 自建** | 免费、快（3 秒/张），但只有 1k、部分模型忽略比例 | `image-generator/scripts/grok_image.py` |
| **E 无可用模型** | 停。只交提示词包 + 出图指引 | — |

★ **噜皮的同步通道不可靠**：`minis-model-use run` 走普通顶层 `prompt/size/n` 时，上游其实把它跑成了异步任务并照常计费，但 App 等不到就放弃，只把 prompt 文本当结果返回、不落图。**对噜皮不要用同步通道出图后宣称已生成**——没有本地文件就是没交付。

## 通道 A 的标准调用

```sh
python3 /var/minis/skills/image-generator/scripts/openminis_image.py generate \
  --model gpt-image-2 --provider 噜皮生图 \
  --prompt "$(cat prompts/01-hero.txt)" \
  --size 1024x1024 --quality auto --n 1 \
  --output /var/minis/attachments/ecom/<slug>/01-hero.png
```

图生图（有产品实拍时必用，一致性远高于文字描述）：

```sh
python3 /var/minis/skills/image-generator/scripts/openminis_image.py edit \
  --model gpt-image-2 --provider 噜皮生图 \
  --image /var/minis/attachments/<产品原图>.png \
  --prompt "$(cat prompts/01-hero.txt)" \
  --size 1024x1024 \
  --output /var/minis/attachments/ecom/<slug>/01-hero.png
```

### 尺寸口径（重要）

OpenAI 系路由**只吃像素尺寸**，不吃 `1:1`、`2:3` 这类比例字符串；写了也会被本地门禁拒或降级为提示词。方法论里的比例必须换算成像素再传：

| 方法论比例 | 用途 | 传参 |
|---|---|---|
| 1:1 | 主图、Amazon / 淘宝主图 | `--size 1024x1024` |
| 2:3 | 详情页竖屏（移动端） | `--size 1024x1536` |
| 4:5 | 详情页 / 信息流竖图 | `--size 1024x1280` |
| 3:4 | 社媒竖图 | `--size 768x1024` |
| 16:9 | Banner、官网 Hero、直播间封面 | `--size 1536x864` |
| 9:16 | 短视频封面、Story | `--size 864x1536` |

★ **像素以本地解码为准，不以请求值为准。** 噜皮实测 `1024x1024` 出的是 `1254×1254`；交付时「清晰度」一栏必须写实际解码尺寸，不能写请求值。

## 通道 B 噜皮异步（批量 / 要 task_id）

```sh
python3 /var/minis/skills/image-generator/scripts/lupi_async.py --transport provider submit \
  --prompt "$(cat prompts/01-hero.txt)" --size 1024x1024 --n 1
python3 /var/minis/skills/image-generator/scripts/lupi_async.py wait \
  --id <task_id> --timeout 600 --download --output 01-hero.png
```

纪律：
- 超时标 `ambiguous`，先 `poll`，**不要换新 Idempotency-Key 重发**——重发就是再花一次积分（该站 10 积分/张）。
- 直链带 `expires` 且拒默认 urllib UA（403），`lupi_async.py` 已处理，别自己写下载。

## 通道 C grok2api（省钱试探）

```sh
python3 /var/minis/skills/image-generator/scripts/grok_image.py gen \
  --prompt "$(cat prompts/01-hero.txt)" --model grok-imagine-image-2.0 --ratio 1:1 --n 1 --json
```

- 实测像素：`1:1→960×960`、`3:2→1152×768`、`2:3→768×1152`、`9:16→720×1280`。
- 只适合**试风格**：确认方向后再用通道 A 出正式尺寸。lite 模型忽略比例，只会出 `832×1248`。

## 通道 D 不可用时

不停摆：完整交出 Image Pack Plan + 全部提示词文件 + 目录结构，并给指引：
- 配模型：[供应商设置](minis://settings/providers) / [模型组](minis://settings/model-groups)

## 排障：先查余额，再查 Key

★ **看到 `Invalid API key` 不要立刻断定 Key 失效。** 2026-10-27 实测：orbitix 账户余额只剩 `$0.3755` 时，`gpt-image-2.5-flare` 返回 `Invalid API key`；签到补到 `$17.46` 后，**同一把 Key、同一个模型**立刻出图成功。

网关把「额度不足」的 402 糊成了 401 的兜底文案，而 `minis-model-use` 的诊断里 `http_status: null`、`error_code: unknown`，等于没留下任何可判定的证据。

**排查顺序**（反了会白折腾）：

1. 看账户余额够不够单张价（余额截图/后台，别先猜）
2. 充值或签到后**原样重试一次**——一秒分出真假
3. 才轮到 Key 轮换、模型白名单、实例错配

同理适用于任何网关：错误文案是兜底时，唯一可信的是「改一个变量重试」的实测。

---

## 批量脚本

`scripts/batch_render.py` 按清单串行调用通道 A，逐张验证落盘、记录实际像素与失败项。

```sh
python3 /var/minis/skills/ecom-visual/scripts/batch_render.py \
  --plan generated-images/<slug>/plan.json \
  --out /var/minis/attachments/ecom/<slug> \
  --model gpt-image-2 --provider 噜皮生图 \
  [--only 01,02] [--dry-run]
```

设计取舍：
- **默认串行**（`--jobs 1`）。付费通道并发限制各家不同（噜皮并发上限 4），超了直接报错，串行最稳；确需并发用 `--jobs 2`。
- **失败即停该张、继续下一张**，最后汇总。不自动重试（超时=结果不确定，重试等于再买一张）。
- **每张独立输出文件**，已存在则跳过（`--force` 才覆盖）。
- `--dry-run` 只打印将要执行的命令与提示词字数，不花钱。

## 费用与节奏

- 单张约 30–90 秒；12–14 张的整包 ≈ 8–20 分钟，远超过单次工具调用时限。
- **必须先报 Image Pack Plan 并经用户确认张数**，再逐张或分批跑。
- 分批时用 `--only` 指定编号，不要把十几张塞进一次调用等超时。

## 交付口径

沿用 image-generator 的六行生图信息（站点 / 模型 / 清晰度 / 比例 / 耗时 / 文件），普通段落、值用行内代码、`文件` 给可点链接。多张时每张一组，不要合并成一个表格糊弄过去。
