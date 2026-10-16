# 规则语法与实现边界

教程基线：mgz0227《书源规则：从入门到入土》，2024-02-27。本文只保留可操作要点，并将“教程宣称”与“客户端实现”分开。

## Default / CSS

- Default：`class.item@tag.a@text`；位置从 0 开始，负数倒数；列表前置 `-` 反序；末尾 `##正则##替换`。
- CSS：以 `@css:` 开头，取值可用 `text`、`textNodes`、`ownText`、`html`、`all`、属性名。
- 实现基于 Jsoup selector，不等同于浏览器 CSS；伪类是否可用取决于目标客户端内置 Jsoup 版本。
- 新规则优先使用基础选择器、属性选择器和结构选择器；复杂伪类必须用目标 Jsoup JAR 或真机验证。
- 详情页若存在稳定的 OpenGraph/业务 meta，可用属性选择器，如 `[property='og:title']@content`；后缀匹配 `[property$='book_name']@content` 仅在命名空间前缀确实变化时使用，须防止同后缀多项误命中。
- 常规下拉分页 URL 取 `option@value`；`select@value` 只有响应明确提供自定义属性时才有依据。下一页/后续页列表的边界检查见 `book-source.md`，不能仅凭 `option:not([selected])` 文本判断成败。
- CSS 组合规则只在整条规则最前面写一次模式头：`@css:A@text&&B@text`。不要写成 `@css:A@text&&@css:B@text`；MD3 的 `AnalyzeByJSoup` 只剥离首个模式头，后一个会被 Jsoup 当作选择器并抛 `SelectorParseException`。

## JSONPath

- 使用 `@json:` 或 `$.` 开头。
- 用于 JSON API；列表根先验证返回类型与数量，再写相对字段规则。
- 不把在线 JSONPath 工具通过当作客户端通过；库版本和配置可能不同。

## XPath

- 使用 `@XPath:` 或 `//` 开头。
- Legado 使用 JsoupXpath，而非 Android/浏览器原生 XPath。
- “W3C XPath 1.0”是教程描述，不代表实现所有函数与轴。
- 已在目标 MD3 日志确认 `normalize-space()` 可抛 `NoSuchFunctionException`；不得用于 MD3 交付。
- `contains()`、`text()`、`position()`等也需按目标版本验证，不能从标准规范推定实现。
- CSS 能表达时不用 XPath；必须使用时，以最小表达式逐步调试。

## JavaScript

- `<js>...</js>` 可位于规则中；`@js:` 只能接在其他规则末尾；上一步结果为 `result`。
- 搜索/发现 URL 的 `{{...}}` 是 JS 表达式，如 `{{key}}`、`{{page}}`、`{{(page-1)*20}}`。
- Rhino 兼容性优先：使用 `var`、普通函数与传统循环；现代语法必须按目标构建测试。
- JS 异常调试时可临时 `return '' + e`，交付前不要吞错后伪装成功。

## 正则三态

- AllInOne：以 `:` 开头，只用于搜索/发现列表、详情预处理和目录列表。
- OnlyOne：`##正则##替换###`，用于非列表字段，只取首个匹配。
- 净化：`##正则##替换`，接在规则后循环替换。
- 跨行显式使用 `[\s\S]` 或相应模式，不依赖 `.` 默认跨行。

### ★替换串遵循 Java 语义，不是 Python 语义（2026-10-16 实测）

`##` 的解析由 `AnalyzeRule.SourceRule.makeUpRule()` 完成，**是把规则串按 `##` 切开**：

```
ruleStrS = rule.split("##")
rule            = ruleStrS[0]      # 选择器/取值
replaceRegex    = ruleStrS[1]      # 匹配段（正则）
replacement     = ruleStrS[2]      # 替换段
replaceFirst    = ruleStrS.size > 3   # 出现第 4 段即「只替换首个」
```

- ★**`replaceRegex` / `replacement` / `replaceFirst` 不是 JSON 字段**，写进书源 JSON 无效（会被忽略）。
  清洗必须写在 `content`（或其它字段）**规则串内部**：`@css:p@text##匹配##替换`。
- ★**最多两段**：`rule##A##B`。写 `##A##B##C` 不是链式替换，而是把 `C` 的**存在**解读为 `replaceFirst=true`。
  需要「先掐前缀再掐后缀」时用**一次替换 + 捕获组**：
  `@css:p.info@text##[\s\S]*?作者：([^\n]*)[\s\S]*##$1`
- **捕获组引用写 `$1`、`$2`**（Java 风格），整匹配写 `$0`。写 `\1` 会字面输出。
- **替换段不要用 `\s`、`\d` 这类转义**：Java 对未知转义抛异常（虽被 `kotlin.runCatching` 吞掉）。
  要匹配空白就把正则写在**匹配段**，替换段保持纯文本。
- ★**`compileRegexCache` 缓存正则 + `runCatching` 吞异常**：正则写错时**不报错**，只是结果为空或原样返回。
  → 规则「看着对却没效果」时，先怀疑替换串语义与 `##` 段数，而不是去改选择器。

### ★列表上下文字段必须带 `@` 取值标记（2026-10-16 实测踩坑）

目录/搜索列表的字段（`chapterName`、`chapterUrl`、`name`、`bookUrl`…）在相对节点上求值，
取值必须写明方式：**`@text`、`@href`**，不能裸写 `text` / `href`。

裸写会被当成 CSS 选择器去解析而抛 `Default 规则缺少 @取值`。
（`text` / `href` 恰好不是合法选择器，所以会报错；若换成合法的标签名则会**静默选错元素**，更隐蔽。）

### ★反爬方向可能相反：正文接口专门拒绝浏览器 UA（2026-10-16 实测）

aabook.net 的 `/_getcontent.php` 对**含浏览器标识的 UA 返回 302**（跳回首页，正文拿不到），
而 `curl/8.5.0`、`python-requests`、`okhttp`、甚至**空 UA** 都能拿到正文（HTTP 200）。

- ✗ `Mozilla/5.0 (Linux; Android 13) … Chrome/120 … Mobile Safari/537.36` → 302
- ✗ `Dalvik/2.1.0 (Linux; U; Android 13)` → 302
- ✓ `curl/8.5.0` / `python-requests/2.31.0` / `okhttp/4.9.0` / 空 UA → 200

**教训**：默认「伪装移动端浏览器 UA」是常见做法，但**不普适**。
遇到「接口 302 跳首页 / 返回 HTML 首页 / 返回空」而 token、cookie、Referer 都正确时，
**先把 UA 换成非浏览器值试一次** —— 成本极低，判别力极强。
另：`curl -L` 会静默跟随 302，把「被拒绝」伪装成「拿到了一个 HTML 页」，排查时先看是否 302。

### 会话型 token 的取用顺序

同一站点的正文 token 绑定 `PHPSESSID`，必须**同一 cookie jar、同一会话**内：
先请求正文页（落 cookie + 取页内 token）→ 立刻用同 jar 请求接口。
中间插入其它请求（或换 jar）都会让 token 失效。

## 连接符与变量

- `&&` 合并、`||` 首个非空、`%%` 交错；教程要求同种规则间使用。
- 常见变量：`baseUrl`、`result`、`book`、`chapter`、`title`、`src`、`cookie`、`cache`。
- `@put/@get` 用于非 JS 规则；`java.put/java.get` 用于 JS。

## ★`searchUrl` 可用 `@js:` 头（2026-10-16 源码核实）

`AnalyzeUrl.initUrl()` 的调用顺序是：

```
ruleUrl = mUrl
analyzeJs()        // ← 先执行 @js:/<js></js>，把 @result 替换进去
replaceKeyPageJs() // ← 才替换 {{key}} / {{page}}
analyzeUrl()
```

而 `evalJS` 的 bindings 里**有 `key`**（`AnalyzeUrl.kt` 第 384 行 `bindings["key"] = key`）。
所以 `@js:` 头**可以读到 `key`**，能在拼 URL 前对它做处理：

```json
"searchUrl": "@js:\"/m/search.html?searchword=\"+java.encodeURI(String(key).replace(/^[\\s\"“”']+|[\\s\"“”']+$/g,\"\"))"
```

**用途**：客户端「精准搜索」开启时会给关键词加引号；若站点不支持短语查询，加引号即 0 结果
（实测本类站点：裸词 60 条 vs 带引号 0 条）。用上述写法把引号剥掉，两种模式都能搜到。

⚠️ **两个易错点**：
1. **只编码关键词，不要编码整串 URL**。写成 `java.encodeURI("/m/search.html?searchword="+key)`
   会把 `?` `=` 也编码成 `%3F` `%3D`，URL 直接失效。
2. 静态校验器会因「未见 `{{key}}`」报 **WARN**——这是**预期**，不是缺陷；
   但要人工确认 JS 里确实读了 `key`。

## `exploreUrl` 的多入口格式

`exploreUrl` 用换行分隔，每行 `分类标题::URL`；URL 里可写 `{{page}}` 供翻页。
一个站点若同时有「分类 / 题材 / 字数 / 状态 / 时间 / 排序」，**每项都写成独立入口**，
不要只写一个 `category.html` 空入口（那会让发现页形同虚设）。

## ★搜索页与发现页结构通常不同，不可复用规则（2026-10-16 实证）

同一站点两套列表页的**容器与字段常常完全不同**，把 `ruleSearch.bookList` 直接搬到
`ruleExplore` 是最常见的「发现页空白」成因。实测对照：

| | 搜索页 | 发现页 |
|---|---|---|
| 容器 | `ul.book-list>li`（每页 15） | `div.book-all-list>ul>li`（每页 30） |
| 书名 | `h5>a.name@text` | `div.right>a.name@text` |
| 作者 | `span.author@text` | `p.info@text##…作者：(\S+)…##$1` |
| 最新章 | — | `p.update>a.chapter@text` |
| 封面 | `div.left>a>img@src` | **无** |
| 状态 | `span.status@text` | **无** |

**做法**：为两页各抓一份真实 HTML，分别定规则；缺的字段（如发现页无封面/状态）
留空 `""` 或 `@js:""`，**不要照抄另一页的规则**（会静默取空或取错元素）。

## 规则验证记录

每个关键规则保存：输入文件/URL、解析器和版本、规则文本、匹配数量、首项、末项。未注明解析器版本的桌面测试只能算“近似验证”。
