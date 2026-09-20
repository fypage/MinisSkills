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

## 连接符与变量

- `&&` 合并、`||` 首个非空、`%%` 交错；教程要求同种规则间使用。
- 常见变量：`baseUrl`、`result`、`book`、`chapter`、`title`、`src`、`cookie`、`cache`。
- `@put/@get` 用于非 JS 规则；`java.put/java.get` 用于 JS。

## 规则验证记录

每个关键规则保存：输入文件/URL、解析器和版本、规则文本、匹配数量、首项、末项。未注明解析器版本的桌面测试只能算“近似验证”。
