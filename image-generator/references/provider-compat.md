# 图像供应商兼容与选择

供应商状态是运行时信息，不写死在技能主流程。每次实际生图前以：

```sh
minis-model-use list --modality image_output
```

为准。只选择当前返回且声明 `image_output` 的模型；用户明确指定供应商或模型时优先服从，并在不存在时停止，不擅自替换为其他付费路由。

## 通用 OpenAI 图像路由

优先使用标准顶层字段：

```json
{
  "prompt": "...",
  "size": "1024x1024",
  "quality": "auto",
  "n": 1,
  "response_format": "url"
}
```

图生图使用本地图片压缩后的 data URI：

```json
{
  "prompt": "仅改变环境；保留人物身份和构图",
  "images": ["data:image/jpeg;base64,..."],
  "size": "1024x1536",
  "n": 1
}
```

这些尺寸仅作格式示例，实际允许值须查供应商文档；比例字符串不是所有 OpenAI 图像端点的通用输入。`images` 是 OpenMinis 的兼容入口，不等于官方 multipart 编辑协议；data URI 会发送给所选供应商。

未知字段可能被供应商忽略；不得仅因请求被接受就宣称分辨率、质量或编辑约束已生效。`extra_body` 不得覆盖核心字段、路由或凭据。

## Gemini 标准输入

仍交给 `minis-model-use` 转换，不手写供应商原生请求体：

```json
{
  "messages": [{"role": "user", "content": "..."}],
  "generation_config": {
    "aspect_ratio": "16:9",
    "image_size": "2K",
    "number_of_images": 1
  }
}
```

图生图使用 OpenAI 消息内容块 `image_url` 携带本地 data URI。数量、质量与分辨率支持依具体模型而定，不静默把不支持的参数当作已生效。离线适配通过不等于远端生图验证。

## 特殊适配

### picpi 皮皮工艺站

历史验证显示，该路由需要 `messages + image_generation tool` 才能可靠提取媒体；不要走普通顶层 `prompt/size/n` 生成路径。图生图引用仍放在顶层 `images` 数组。

此适配只在运行时供应商标签精确匹配时启用。仅支持 n=1；size 作为提示词并警告，不保证像素；非默认 quality、resolution、response-format 及 extra-body 拒绝。默认 response-format=url 也不控制工具响应格式。若供应商改名或协议升级，应先做一次受控验证，再更新脚本与测试。

## 包装器能力边界（v1.2）

- OpenAI size须为auto或正整数WxH；quality允许auto/low/medium/high/standard/hd，未知值本地拒绝。这是语法门禁，不证明每个供应商支持所有枚举。
- Gemini像素尺寸只在精确约分后属于支持比例时转换，不再容差吸附。
- ambiguous任务保留本次stage与verified_media；images表示已发布图片；recovery_candidates仅为未验证附件URL，不得直接当成生成成果。检查日志中的cleanup_status/cleanup_errors；保留目录不是清理失败，也不是远端已取消。
- 原子无覆盖发布依赖硬链接支持，不支持时安全失败并保留源图。SIGKILL或断电无法保证清理/持久性，不自动清理历史任务。

- Gemini 按列表 provider_type 为 Gemini/Google/GoogleAI 识别，不猜模型名。数量1–4；比例仅1:1、16:9、9:16、4:3、3:4；resolution 映射 image_size。非默认 quality/response-format 和 extra-body 拒绝。
- OpenAI 数量1–5；resolution 通过 extra_body.resolution 传递并警告，这是供应商扩展，不保证生效。
- 多图从 CLI 媒体数组提取，逐张完整解码、按文件 SHA-256 去重；返回 images、requested_n、actual_n。仅自动接收本次唯一暂存目录中的文件，防止旧图误交付。
- CLI 若把额外图片保存到暂存目录外、只给HTTP链接或跨UID不可读URL，不自动下载或冒充验证成功；报告缺图，零张为结果不确定。若已拿到有效原媒体URL，可按主规范尝试恢复，不能重新生图。
- 日志不转储原始CLI响应，防止提示词或data URI回显；CLI参数警告只作存在性提示。远端支持情况仍需单独授权生图验证。

## 失败与费用边界

- `502`、`503`、`524`、连接重置、读取超时及未知提交后异常：结果不确定，可能已经创建任务并计费；不自动重试或切换供应商。
- 明确的模型不存在/参数拒绝可归类为拒绝；不能仅凭非零进程退出码推断未执行或未计费。仍不擅自改用另一个付费供应商。
- 只有能证明请求尚未提交的本地参数错误或进程启动失败，才可修正后重试。
- 有任务查询 API 时，必须按供应商文档，以模型、时间、参数和终态精确匹配；没有证据不声称成功、失败、退款或扣费。

`wisart-api.md` 仅保存历史恢复资料，不作为当前供应商状态来源；`grsai-option-audit.md` 是未并入后端的审计记录。
