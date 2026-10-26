---
name: legado-source-development
description: 开发、修复、迁移、审计和测试 Legado（阅读3.0）书源与 RSS 订阅源，兼容 HapeLee/legado-with-MD3。处理 Default/CSS/JSONPath/XPath/JS/正则、搜索/发现/详情/目录/正文、分页、URL 请求、Cookie/WebView、导入 JSON、调试日志与 MD3 扩展。触发词：Legado、阅读3.0、MD3阅读、书源、订阅源、RSS源、ruleSearch、ruleToc、ruleContent、ruleArticles、sourceUrl。
version: 4.2.0
---

# Legado / MD3 规则开发

## 一、开局三件事

1. **定对象**：书源（`bookSourceUrl`/`bookSourceName`，链路 搜索·发现→详情→目录→正文）还是 RSS（`sourceUrl`/`sourceName`，链路 文章列表→描述或正文）。两者文件形态与校验器不可混用。
2. **定任务**：新建 / 修复 / 迁移 / 审计 / 答疑。
3. **定验证天花板**：本机沙箱只有**静态层与规则层**（Python 实现），JVM 同版本引擎与真机均须在别处完成。**先声明会把交付物标到哪一层**（见 §六），再动手。

按需读取：

| 需要什么 | 读哪份 |
|---|---|
| 通用语法（Default/CSS/JSONPath/XPath/JS/正则/连接符） | `references/rule-syntax.md` |
| 书源字段与四段链路 | `references/book-source.md` |
| RSS 订阅源 | `references/rss-source.md` |
| URL 选项、编码、Cookie、WebView、JS 宿主 | `references/request-js.md` |
| MD3 差异、解析器版本、导入契约 | `references/md3-compat.md` |
| 验证分层、沙箱、交付门槛 | `references/testing.md` |
| 本技能如何自检、案例存档、版本表 | `references/maintenance.md` |
| **实战案例复盘（先读这个）** | `references/cases/` — 每案一节「为什么没测出来」 |

## 二、非协商约束（硬约束）

这些不是建议，违反即交付失败。

1. **不得跨层报成功**。沙箱通过、JVM 通过、真机通过是三件事；缺层即为「未验证」，不得用低层结果替代。
2. **不得臆造选择器、接口或结论**。没有响应样本就交付「分析框架 + 待验证草稿」，不写「应该能用」。
3. **不得用零散探针冒充统一门禁**。具体源必须跑统一 runner 并查看 `report.json` 与 `ISSUES`；探针只用于定位。
4. **不得覆盖已发送的成品**。修订一律新文件名 + 版本递增（`site.v2.json`），旧版保留摘要。
5. **不得让用户从 Markdown 代码块手工复制书源**。粘贴交付必须走 `copy_source.py`（纯 JSON + Gson 探针 + 直写剪贴板）。
6. **不得把浏览器 Elements DOM 当作网络响应样本**。`querySelector` 结果也不能冒充 Jsoup 结果。
7. **正文分页只跟同一章节**。`nextContentUrl` 命中「下一章/下章」或章节 ID 变化即须停止，禁止串章。
8. **CSS 组合规则模式头只写一次**（`@css:A@text&&B@text`）。分支前重复 `@css:` 会被 Jsoup 当选择器解析并抛错。
9. **交付不得无 SHA-256**。报告须含文件版本、验证层级、已知限制、回滚路径。
10. **凭据与 Cookie 不回显**。聊天与报告只写字段名与路径，不写值。

## 三、证据优先级

冲突时依次采用：

1. 用户目标 APK 的**真机日志与可复现行为**；
2. 该 APK 对应**版本源码**；
3. 用户指定教程（mgz0227，2024-02-27）；
4. 解析库文档（Jsoup、JsonPath、JsoupXpath、Rhino）；
5. 社区资料与真实书源样本；
6. 经验推断。

每条结论须显式归类：`源码确认` / `样本验证` / `静态推断` / `未知`。
教程声称符合某标准 ≠ 客户端实现了该标准全部能力。

### 外部参考审计

- `DandanLLab/legadoSkill` 仅作社区参考，审计基线 commit `d988cf232632931c3f8c7c5e5dd6714cd8a75cf6`（2026-03-16）。
- **可吸收**：原始 HTTP 响应取证、请求/响应编码分离、目录下拉分页、API 多页 URL 列表、JS 返回类型、语义化 meta 属性提取。
- **不吸收**：其 Python 模拟调试器、Node 模拟 Rhino、自动修复、以及「规则存在即正确」式检查——这些不能替代目标同版本解析器与真机。
- 社区文档示例同样须复核。例如正文 `nextContentUrl` 只跟**同一章节的下一内容页**，「下一章」链接不得作为正文分页。

## 四、任务输入与交付契约

| 任务 | 最少需要 | 只给了不够时的产出 |
|---|---|---|
| 新建书源/RSS | 站点入口 URL（如需登录/搜索/特定版本则一并给） | 分析框架或待验证草稿，标明缺什么 |
| 修复现有源 | 原始 JSON、报错全文、失败阶段、目标 APK/MD3 版本、相关响应样本 | 定位方向，**不得称已修复** |
| 迁移（通用→MD3 或反向） | 源文件、两边差异点、目标版本 | 迁移对照表 + 未验证项 |
| 审计 | 源文件（+ 目标版本） | 静态与规则层审计报告 |
| 知识问答 | — | 分层标注答案依据等级 |

只给截图时可以定位方向，不能据此声称修复完成。

### 降级状态（四层，跨层表述即违规）

- `JSON_OK`：JSON、重复键、类型、静态字段通过。
- `RULE_REF_OK`：保存响应在**本机参考执行器**通过（Python 实现，与目标引擎存在
  版本偏差）。若在目标同版本 JVM 引擎通过，升格记 `RULE_SAMPLE_OK`。
- `NETWORK_OK`：实时请求成功且结果语义正确。
- `DEVICE_OK`：目标 APK 导入 + 调试日志通过。

**跨层表述即违规**：`RULE_REF_OK` 不等于 `RULE_SAMPLE_OK`，更不等于「可用」。
本沙箱 JVM 不可用的前提下，能给出的最高规则层结论是 `RULE_REF_OK`，
且必须附「未评估项清单」（`SKIPPED`）。

## 五、工作目录与产物约定

- 成品：`/var/minis/shared/legado/sources/`（多版本并存，不覆盖）
- 响应样本与测试记录：`/var/minis/shared/legado/analysis/<site>/`
- 沙箱与报告：`/var/minis/shared/legado/sandbox/`
- 技能自检、案例、版本表：`/var/minis/shared/legado/skill-refactor/`
- **不在 Skill 目录保存用户成品**；`workspace/`、`attachments/` 会被清空，只当草稿区。
- 修订命名：`site.v1.json` → `site.v2.json`；保留下各版 SHA-256、变更点、验证层级。

## 六、开发流程

### 1. 建立样本基线

保存最小但完整的**原始 HTTP 响应字节**及解码副本，覆盖：

搜索 / 发现 / 详情 / 目录首·中·末页 / 正文首·续·末页。

每份样本记录：请求 URL、方法、状态、最终 URL、Content-Type、响应头 charset、HTML meta charset、实际采用编码、必要 header/Cookie。

- 不用 `DOCTYPE`、注释、缩进或隐藏元素的有无判断「真实性」——这些都不可靠。
- 动态站先定位 XHR/fetch；API 不可复用时才考虑 webView。
- WebView 场景可另存渲染后 DOM，但**必须与原始响应分开标注**。
- 二进制响应原样保存，避免错误解码后无法复核。

### 2. 编码：两个字符集必须分开验证

| 问题 | 对象 | 判据 |
|---|---|---|
| 响应解码字符集 | 响应字节 → 文本 | 响应头 → BOM → HTML meta → 可逆解码 → 样本文字，综合判断 |
| 请求参数字符集 | query / 表单值的 percent-encoding | 必须对照浏览器或 HAR 的真实请求验证 |

**响应是 GBK 不必然推出请求参数也是 GBK。**
`url_charset` 是工具专用字段，**不是 Legado URL 选项**，不得写入书源。
Legado 端若确需非 UTF-8 参数，按目标源码与真机验证 `java.encodeURI(key,'GBK')` 等实现，并防二次编码。
解码禁止 `errors='ignore'` 静默丢字；失败须保留原始字节并明确报错。

### 3. 选最小技术栈

| 场景 | 首选 | 备注 |
|---|---|---|
| HTML | Default / CSS | 详情页可用稳定的 `meta[property]`，但须响应原文确有该值 |
| JSON | JSONPath | 先验列表根类型与数量，再写相对字段规则 |
| 稳定文本 | 正则 | 不用正则承担脆弱 DOM 解析 |
| 签名/解密/跨页聚合 | JS | 返回类型须匹配宿主契约（`references/request-js.md`） |
| 确需渲染或嗅探 | WebView | 仅在此链路才用 |

禁止因教程标注「XPath 1.0」就假设函数齐全。**未在目标 JsoupXpath 验证的函数不进交付规则**；优先用 CSS/Default 替代。

### 4. 按依赖顺序实现

**书源**：`searchUrl + ruleSearch` → `exploreUrl + ruleExplore`（需要时）→ `ruleBookInfo` → `ruleToc`（含分页与停止条件）→ `ruleContent`（含分页、净化、媒体）→ MD3 扩展最后加。

**RSS**：`sourceUrl/sourceName` → 标准 RSS 无需自定义 `ruleArticles` → 非标准页面实现列表/标题/链接 → 再决定描述规则或正文规则 → **单独验证上拉分页**（不套用书源 `{{page}}` 逻辑）。

### 5. 每层立刻验证

对保存响应执行实际选择器 / JSONPath / 正则，至少记录：匹配数量、首项、末项、URL 解析结果。

MD3 基线解析器版本：Jsoup `1.16.2`、JsoupXpath `2.5.5`、JsonPath `3.0.0`、Rhino `1.8.1`、Gson `2.14.0`。版本不同只能记为近似验证。

### 6. 分页边界（必查五项）

1. 第一页能取得下一页；
2. 中间页不会回到当前页或前页；
3. 末页返回空并终止；
4. 合并后无重复、无漏项、顺序正确；
5. 「下一本 / 下一章 / 目录」等邻近链接不会误命中。

目录的三种分页形态（单 URL、URL 列表、`select` 下拉）取值与边界见 `references/book-source.md`；
JS 返回类型见 `references/request-js.md`。逐页跟随与一次枚举是两种策略，按目标实现选，不互相强加。

### 7. 修复纪律

1. 保留错误全文、输入 URL、时间、目标 APK 版本；
2. **精确定位失败阶段**——「页面获取成功」≠「模块成功」；
3. 修复后重跑受影响模块**及上下游链路**；
4. 只消除异常而没验证结果内容，**不算修复完成**；
5. 不凭一次截图猜导入入口、对象/数组要求或缓存原因。

## 七、验证与门禁

### 0. 五页签调试面板（本机可用，对标 Legado 调试页）

```sh
python3 /var/minis/skills/legado-source-development/scripts/debug_source.py source.json \
    --what all --key 逍遥 --book 964
# --what search|explore|info|toc|content|all
# --url  指定页面（详情/目录/正文页签）；缺省则用 bookSourceUrl / --book 推算
# --cat  发现页分类名        --page 翻页页码
```

每页签输出「真实请求 URL（含方法）＋ HTTP 码 ＋ 长度 ＋ 解析结果」，同时暴露
解析器自身的失败（`⚠ 解析异常`）与不支持语法（`⚠ 未支持`）。

**站点无关**：站点根取自 `bookSourceUrl`，不含任何硬编码站点。

**已验证支持**：`@css:` 及其取值后缀（`@text/@href/@src/@data-*`）、`##正则##替换`
（含 `$1`→`\g<1>` 换算）、`<js>...</js>` 值后处理、`tag.a.0@href` 简写、
`:eq(n)`/`:lt/:gt/:first/:last`、JSON 数组与「组名::地址」两种 exploreUrl、
`<,{{page}}>` 可选分页段、`{{key}}`（自动 URL 编码）、GET/POST（含
`,{"method":"POST","body":...}` 选项）、相对 URL 自动补全。
**明确不支持并会提示**：JSONPath（`$.`）、XPath（`//`）—— 真机由 Legado 解析。

**用法要点**

- `@js:` 规则交给 node 真跑（`scripts/exec_js_rule_node.py`），
  `java.ajax` 用 `execSync('curl ...')` 同步实现，最贴近 Rhino 语义。
- 正文页按**内容特征**判定真伪，不看长度（见下「反爬镜像站」）。
- 回归：`python3 scripts/test_debug_parser.py`（64 项解析器断言）。

**★失败分型（2026-10-26 新增）**：取不到东西时不再一律报「规则写错了」，而是打一行
`✗ [phase.CODE] 字段 xxx —— 原因`，便于直接定位。当前码表：

| 码 | 含义 | 处置 |
|---|---|---|
| `SELECTOR_EMPTY` | 容器匹配 0 个节点 | 先确认响应是否目标页 |
| `HARNESS_UNSUPPORTED` | xpath / `@js:` 容器本脚本无法求值 | **记「未评估」，不是源的缺陷** |
| `TOC_SELECTOR_EMPTY` | chapterList 完全没匹配 | 改 ruleToc.chapterList |
| `TOC_EMPTY` | 容器命中但章节名全空 | 查 chapterName 是否带 `@text` |
| `CONTENT_EMPTY` | 取值为空 | 查 ruleContent.content |
| `CONTENT_TOO_SHORT` | < 100 字符 | 同上 |
| `CONTENT_IS_LOGIN_PAGE` | 响应像登录页 | 需 Cookie/登录态 |
| `CONTENT_IS_CAPTCHA_PAGE` | Cloudflare 人机验证 | 不可自动绕过，停并汇报 |
| `CONTENT_IS_VIP_LOCK_PAGE` | 付费/会员提示 | 只能记 degraded |
| `CONTENT_IS_CSR_SHELL` | 前端空壳 | 需 webView/webJs |
| `HTTP_BLOCKED` | 4xx/5xx | 看状态码 |

`HARNESS_UNSUPPORTED` 只表示本脚本能力边界，**不得据此判定书源有缺陷**。
回归：`python3 scripts/test_debug_classify.py`（13 项）。

**★判读纪律**：调试脚本报「HTTP 400/403/000」时，先手动 `curl` 同一 URL 对照，
再决定是站点故障、风控，还是脚本自身缺陷。**不要把脚本的缺陷当成规则错误去改规则。**

### 1. 静态校验（本机可用）

```sh
python3 /var/minis/skills/legado-source-development/scripts/validate_source.py source.json
python3 /var/minis/skills/legado-source-development/scripts/validate_source.py --strict source.json
python3 /var/minis/skills/legado-source-development/scripts/validate_source.py --json --target md3 --kind auto source.json
```

选项：`--strict`（有警告即非零）、`--json`、`--target common|md3`、`--kind auto|book|rss`。

**静态 PASS 只代表 JSON 与已知风险检查通过**，不代表网络、解析器或真机可用。

**★新增静态铁律（2026-10-26，借自上游 official-rule-pack.json，均为纯字符串判定）**：

| 检查 | 级别 | 说明 |
|---|---|---|
| `;post=` / `;get=` | error | 请求选项必须写在 URL 后的 JSON（method/body/headers） |
| jQuery 伪类 `:has/:visible/:hidden` | error | **注意**：`:contains()` 不要报错——参考执行器（soupsieve）可用，成品源大量在用；目标端是否生效须真机核实。`:eq()` 属目标客户端自有扩展，也不报 |
| `@css:…@text@js:…` 多 action 链 | error | Legado 按「最后一个 `@`」切分，前面的 `@text` 会进选择器；改 `##$##<js>` |
| `ruleBookInfo.summary` | error | 详情简介真名是 `intro`，写 summary 静默为空 |
| User-Agent 完整性 | warning | 有 `KHTML/Gecko` 缺 `Chrome/`+`Safari/` 尾段，或被判为脚本客户端 |

UA 检查只针对能静态解析成 JSON 的 header；含 `{{ }}`/`<js>`/`@js:` 的模板值跳过（留给真机）。
回归：`python3 scripts/test_validator_lint.py`（17 项）、`python3 scripts/test_debug_classify.py`（13 项）。


### 2. 规则执行（本机可用，Python 参考实现）

```sh
S=/var/minis/skills/legado-source-development/scripts
python3 $S/sandbox_runner.py source.json --fixtures fixtures.json --all --assert
```

**单一入口，别再拼散装命令**（旧沙箱的 `run_source_module.sh` 已废弃，它在本沙箱内
会因 JVM 起不来而失败）。`sandbox_runner.py` 一跑即完成：静态校验 → 各模块参考执行
→ 纯 JSON 传输校验 → 导入探针 → 断言，产出 `report.json`。

这是**规则层参考执行器**，不是 JVM 同版本引擎。产出 `report.json`，issue 分
`STATIC / TRANSPORT / RULE / EMPTY / HARNESS / SKIPPED`；`--assert` 下存在**硬失败**
（除 `SKIPPED` 外）返回非零。

**★必须分清 `HARNESS` 与 `RULE`**：`HARNESS` 表示参考执行器没有该宿主能力
（JS、WebView、`@put/@get` 等），连带产生的期望不符标为 `SKIPPED` —— 含义是
「**未评估**」，既不是通过、也不是源的缺陷。交付时必须如实单列。

支持范围与 JVM 沙箱的差别见 `references/testing.md`；未实现的宿主调用**必须显式
报出**，不得静默跳过（静默跳过会把「没测」伪装成「通过」）。

### 2.5 交付（剪贴板受前台限制）

```sh
python3 $S/copy_source.py source.json      # 生成纯 JSON → 写剪贴板 → 跑导入探针
```

`android-clipboard` 在 App 非前台时返回 `clipboard_requires_foreground`（Android 10+
限制），**这是环境限制不是脚本缺陷**。遇到时告诉用户把 Minis 切到前台再重试；
或用 `prepare_clipboard.py -o out.json` 只生成文件，让用户自行复制。

### 3. JVM 同版本引擎（本机不可用）
`/var/minis/shared/legado/sandbox/` 备有全套同版本 JAR 与探针源码，**但在本沙箱内
JVM 无法启动**：PRoot/Android seccomp 禁止标记可执行内存页，OpenJDK 21 直接报
`Failed to mark memory page as executable - check if grsecurity/PaX is enabled`。
这不是配置问题，`-Xint` 等参数也绕不过。

- **不要**把 JVM 沙箱当可用门禁；先跑探针确认真实状态：
  ```sh
  python3 $S/jvm_probe.py     # {"available": false, "reason": "no_exec_mem", ...}
  ```
- `sandbox_runner.py` 会**自动调用该探针**并把结果写进 `report.json.stages.jvm`；
  不可用时明文降级（`engine: python-reference (jvm unavailable)`）并追加 note，
  绝不伪装成同引擎通过。
- 同理，导入探针会降级为 `python-json` 并标 `degraded: true`。
- JVM 可用时（换允许 JIT 的宿主，或同机代理），`sandbox_runner.py` 会自动切回
  Gson 探针，无需改调用方式。
- **结论口径**：JVM 缺席时，规则层结论只能是「参考执行器通过 / 未评估项待补」，
  **不得**宣称同引擎验证通过。

### 4. 目标客户端调试

| 模块 | 调试输入 |
|---|---|
| 搜索 | 关键字 |
| 发现 | `分类::URL` |
| 详情 | 详情 URL |
| 目录 | `++目录URL` |
| 正文 | `--章节URL` |

MD3 调试页可能自动补 `++`/`--`，以目标构建行为为准。**保存完整日志**，不只截最后一行。

## 八、交付门槛

交付包必须含：

1. 新版本文件名的 JSON（不覆盖旧版）；
2. 类型（书源/RSS）、目标客户端与导入入口；
3. 文件顶层形态（对象/数组）及依据；
4. 纯 JSON 传输副本 + 导入探针结果 —— 用 `copy_source.py` 交付粘贴版，不让用户手选；
5. 静态校验结果；
6. 验证矩阵：逐项标明属 保存响应 / 实时网络 / 真机 哪一层；
7. 分页终止边界结果（五项全列）；
8. 已知限制与未验证项；
9. SHA-256 与回滚文件路径。

**没有目标客户端验证时，一律标「待真机验证」**，不得写「可用」「修复完成」「兼容通过」。

### 发布报告模板

```text
目标：MD3 <版本/提交>
文件：site.vN.json
JSON：PASS
样本规则：PASS（解析器版本；JVM 不可用时标 APPROX）
实时网络：PASS / 未测
真机：PASS / 用户待测 / 未测
分页：首/中/末页结果
已知限制：...
SHA-256：...
```
