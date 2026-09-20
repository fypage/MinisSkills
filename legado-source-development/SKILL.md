---
name: legado-source-development
description: 开发、修复、迁移、审计和测试 Legado（阅读3.0）书源与 RSS 订阅源，并兼容 HapeLee/legado-with-MD3；处理 Default/CSS/JSONPath/XPath/JS/正则规则、搜索/发现/详情/目录/正文、分页、URL 请求、Cookie/WebView、导入 JSON、调试日志及 MD3 扩展。触发词：Legado、阅读3.0、MD3阅读、书源、订阅源、RSS源、ruleSearch、ruleToc、ruleContent、ruleArticles、sourceUrl。
version: 3.1.0
---

# Legado / MD3 规则开发

## 一、先分流

1. 判断任务是**书源**还是 **RSS 订阅源**：
   - 书源主键：`bookSourceUrl`、`bookSourceName`，链路为搜索/发现→详情→目录→正文。
   - RSS 主键：`sourceUrl`、`sourceName`，链路为文章列表→描述或正文。
2. 仅当客户端差异会影响字段或规则时询问目标版本；否则按通用 Legado 制作，并标明未验证的 MD3 扩展。
3. 按需读取：
   - 通用语法：`references/rule-syntax.md`
   - 书源字段与流程：`references/book-source.md`
   - RSS：`references/rss-source.md`
   - 请求与 JS：`references/request-js.md`
   - MD3 差异与导入：`references/md3-compat.md`
   - 验证与交付：`references/testing.md`

## 二、证据优先级

发生冲突时依次采用：

1. 用户目标 APK 的真机日志与可复现行为；
2. 该 APK 对应版本源码；
3. 用户指定教程（mgz0227，更新于 2024-02-27）；
4. 解析库文档（Jsoup、JsonPath、JsoupXpath、Rhino）；
5. 社区资料与真实书源样本；
6. 经验推断。

必须区分“源码确认”“样本验证”“静态推断”和“未知”。教程声称符合某标准，不等于客户端实现了标准全部能力。

### 外部参考审计

- `DandanLLab/legadoSkill` 仅作社区参考，当前审计基线为 commit `d988cf232632931c3f8c7c5e5dd6714cd8a75cf6`（2026-03-16）。
- 可吸收：原始 HTTP 响应取证、请求/响应编码分离、目录下拉分页、API 多页 URL 列表、JS 返回类型和语义化 meta 属性提取。
- 不直接复制其 Python 模拟调试器、Node 模拟 Rhino、自动修复或“规则存在即正确”的检查；这些不能替代目标同版本解析器与真机。
- 社区文档示例也须复核。例如正文 `nextContentUrl` 只应跟随**同一章节的下一内容页**；“下一章”链接不得作为正文分页，否则会串章。

## 任务输入与交付契约

### 新建书源/RSS

最少需要站点入口 URL；若站点需要登录、搜索词、特定客户端版本或已有抓包，应一并提供。缺少关键响应时可以交付分析框架或待验证草稿，但不得臆造选择器、接口或成功结论。

### 修复现有源

优先需要原始 JSON、报错全文、失败阶段、目标 APK/MD3 版本和相关响应样本。只给截图时可定位方向，不能据此声称已修复。

### 知识问答

区分“标准/教程说法”“目标源码确认”“保存响应验证”“实时网络验证”“真机验证”。社区案例只能作为候选，不自动升级为规范。

### 降级状态

- `JSON_OK`：JSON、重复键和静态字段通过；
- `RULE_SAMPLE_OK`：保存响应在目标同版本解析器通过；版本不同为 `RULE_APPROX_OK`；
- `NETWORK_OK`：实时请求和结果语义通过；
- `DEVICE_OK`：目标 APK 导入及调试日志通过。

缺少后一层时，不得用前一层的结果替代。交付报告必须写明输入、验证层级、未验证项、已知限制、文件版本和 SHA-256。

## 三、工作目录

- 成品：`/var/minis/shared/legado/sources/`
- 分析响应与测试记录：`/var/minis/shared/legado/analysis/<site>/`
- 不在 Skill 目录保存用户成品。
- 已发送版本不得同名覆盖；修订版使用 `name.v2.json`、`name.v3.json`，并保留旧版摘要。

## 四、开发流程

### 1. 建立样本基线

保存最小但完整的**原始 HTTP 响应字节**及解码副本：搜索、发现、详情、目录首/中/末页、正文首/续/末页；记录请求 URL、方法、状态、最终 URL、Content-Type、响应头 charset、HTML meta charset、实际采用编码、必要 header/Cookie。不要以 `DOCTYPE`、注释、缩进或隐藏元素的存在与否判断“真实性”，这些都不是可靠证据。

动态站先定位 XHR/fetch；API 不可复用时再考虑 webView。浏览器 Elements DOM 只能证明渲染结果，不等同网络响应；若规则明确运行在 WebView，可另存渲染后 DOM，并与原始响应分开标注。

对 GBK/Big5 等站点，必须分开验证：

- **响应解码字符集**：响应体字节如何转为文本；
- **请求参数字符集**：查询参数或表单值如何 percent-encode。

二者可能不同。不能因响应是 GBK 就推断请求参数也必须 GBK；需用真实搜索请求对照验证。保存二进制响应，避免错误解码后无法复核。

### 2. 选择最小技术栈

- HTML：优先 Default/CSS；详情页可优先检查稳定的 `meta[property]` / OpenGraph 数据，但须以响应原文确有该值为准；XPath 只用于 CSS 难表达且已在目标引擎验证的结构。
- JSON：JSONPath。
- 稳定文本：正则；避免用正则承担脆弱 DOM 解析。
- JS：优先用于请求签名、解密、跨页聚合或规则语法难以表达的问题；返回类型须匹配具体宿主契约，详见 `references/request-js.md`。
- WebView：仅用于确实依赖渲染、页面脚本或媒体嗅探的链路。

禁止因教程标注“XPath 1.0”便假设全部 XPath 函数可用。未在目标 JsoupXpath 验证的函数不得进入交付规则；优先用 CSS/Default 替代。

### 3. 按依赖实现

书源：

1. `searchUrl + ruleSearch`
2. `exploreUrl + ruleExplore`（需要时）
3. `ruleBookInfo`
4. `ruleToc`，含目录分页和停止条件
5. `ruleContent`，含正文分页、净化和媒体/图片
6. MD3 扩展最后添加

RSS：

1. `sourceUrl/sourceName`
2. 标准 RSS 无需自定义 `ruleArticles`
3. 非标准页面实现列表、标题、链接
4. 再决定使用描述规则或正文规则
5. 单独验证上拉分页；不要套用书源 `{{page}}` 逻辑

### 4. 每层立即验证

对保存响应执行实际选择器/JSONPath/正则测试，至少记录：匹配数量、首项、末项、URL 解析结果。MD3 基线应使用 Jsoup 1.16.2、JsoupXpath 2.5.5、JsonPath 3.0.0、Rhino 1.8.1；版本不同只能记为近似验证。不能用浏览器 `querySelector` 结果冒充 Jsoup 结果。

### 5. 模块级同版本回归

有保存响应时，优先运行 `/var/minis/shared/legado/sandbox/run_source_module.sh`，让列表规则建立真实节点上下文，再逐项执行字段规则。单独测试 CSS selector 不能替代模块回归；组合模式头、相对 URL、字段后处理等只有模块执行才能暴露。

当前回归器已覆盖常用 Default、CSS/XPath/JSONPath、Rhino 列表/字段链及常见编码解密宿主；WebView、Cookie、Android 文件和完整网络生命周期仍须真机验证。未实现的宿主调用必须明确失败，不得静默跳过。

参考聚阅成品沙箱，具体书源统一使用：

```sh
cd /var/minis/shared/legado/sandbox
./run.py source.json --fixtures fixtures.json --all --transport --assert
```

必须查看生成的 `report.json` 与 `ISSUES`；不得用若干零散探针通过代替统一门禁。沙箱自身回归入口为 `run_all_tests.sh`。

### 6. 分页边界

目录和正文分页至少验证：

- 第一页能取得下一页；
- 中间页不会回到当前页或前页；
- 末页返回空并终止；
- 合并后无重复、无漏项、顺序正确；
- “下一本/下一章/目录”等邻近链接不会误命中。

目录单 URL、URL 列表与 `select` 分页的取值及边界见 `references/book-source.md`；JS 返回类型见 `references/request-js.md`。按目标实现区分逐页跟随和一次枚举，不将同一遍历策略强加给所有源。

正文 `nextContentUrl` 仅用于**同一章节的续页**。应以 URL 规律、章节标题/ID 或正文页标记验证结果，排除实际指向下一章的候选。规则中出现“下一章/下章”可能是在排除该链接，不能只凭文字判错。无法可靠区分时留空并标注限制。

### 7. 修复纪律

收到报错后：

1. 保留错误全文、输入 URL、时间和目标 APK 版本；
2. 精确定位失败阶段，不把“页面获取成功”说成“模块成功”；
3. 修复后重跑受影响模块及上下游链路；
4. 只消除异常而未验证结果内容，不算修复完成；
5. 不依据一次截图猜测导入入口、对象/数组要求或缓存原因。

## 五、静态校验

```sh
python3 /var/minis/skills/legado-source-development/scripts/validate_source.py source.json
python3 /var/minis/skills/legado-source-development/scripts/validate_source.py --strict source.json
python3 /var/minis/skills/legado-source-development/scripts/validate_source.py --json source.json
```

静态 PASS 只表示 JSON 和已知风险检查通过，不表示网络、解析器或真机可用。

## 六、目标客户端调试

书源调试输入：

- 搜索：关键字
- 发现：`分类::URL`
- 详情：详情 URL
- 目录：`++目录URL`
- 正文：`--章节URL`

MD3 调试页可能自动添加 `++`/`--`；以目标构建行为为准。保存完整日志，不只截取最后一行。

## 七、交付门槛

交付必须包含：

- 使用新版本文件名的 JSON；
- 类型（书源/RSS）、目标客户端与导入入口；
- 文件顶层形态（对象/数组）及依据；
- 纯 JSON 传输副本与 Gson 导入探针结果；粘贴交付使用 `copy_source.py`，不要求用户从 Markdown 代码块手选全文；
- 静态校验结果；
- 模块回归矩阵，明确哪些是保存响应验证、实时网络验证、真机验证；
- 分页终止边界结果；
- 已知限制与未验证项；
- SHA-256 与回滚文件。

没有目标客户端验证时只能标为“待真机验证”，不得称“可用”“修复完成”或“兼容通过”。
