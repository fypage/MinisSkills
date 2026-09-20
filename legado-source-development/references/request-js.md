# URL 请求、Cookie、WebView 与 JS

## URL 选项

常见格式：

```text
URL,{"method":"POST","charset":"gbk","body":"key={{key}}","headers":{"Referer":"..."},"webView":true,"retry":1}
```

教程 2024 示例仅列常见参数，不是现代客户端完整契约。目标 MD3 基线 `AnalyzeUrl.UrlOption` 还包含 `HEAD`、`origin`、`webJs`、`dnsIp`、`bodyJs`、`serverID`、`webViewDelayTime` 等；以目标源码为准。

URL 选项可能包含嵌套 `headers`，静态提取必须做括号/字符串感知，不能简单 `rfind(',{')`。

## 请求与响应取证

记录方法、最终 URL、状态码、Content-Type、重定向、请求头字段名和 Cookie 是否需要。保存原始响应字节、响应头和解码后的 fixture；不要把浏览器 Elements DOM 当作普通网络请求响应。

把两类字符集分开：

- 响应 `charset`：用于把响应字节解码为文本；按响应头、BOM、HTML meta、可逆解码和样本文字综合判断。
- 请求参数编码：用于 GET query 或 `application/x-www-form-urlencoded` 表单的 percent-encoding；必须对照浏览器/HAR 的真实请求验证。

响应为 GBK 不必然意味着请求参数也采用 GBK。工具专用的 `url_charset` 不是 Legado URL 选项字段，不得直接写进书源。Legado 端若需非 UTF-8 参数，应按目标源码和真机验证 `java.encodeURI(key, 'GBK')` 等实现，并避免二次编码。解码时禁止 `errors='ignore'` 静默丢字；失败应保留原始字节并明确报错。

header 顶层通常是 JSON 字符串；动态 header JS 应返回 JSON 字符串。请求体在目标实现要求字符串时显式 `String(body)`。

标准请求头使用 `Referer`；不要把教程正文图片示例里的 `Referrer` 无条件照搬。

## API / 搜索接口发现顺序

站点内容不是静态 HTML 时，按以下顺序取证，禁止大规模猜测 `/search` 等路径：

1. 浏览器 Network/XHR/fetch 记录：确认真实方法、URL、query/body、Content-Type、Origin/Referer、Cookie、响应类型与最终 URL；
2. 检查 `<form>` 的 `action`、`method`、`input name` 和提交编码；
3. 搜索内联脚本中的 `fetch`、XHR、axios、jQuery AJAX、`search`、`api`、`ajax`；
4. 下载实际引用的外部 JS，结合 source map、相对路径和运行时 base path 分析接口；
5. 仅对少量有证据的候选 URL 做独立请求复现；
6. 最后参考相似站点案例，不以案例替代当前站点验证。

每个候选接口记录：发起页面、方法、完整 URL、参数/请求体、Content-Type、Origin/Referer、Cookie需求、状态码、最终 URL、返回类型、目标数据字段及复现结果。搜索建议接口、自动补全接口和真正的搜索结果接口必须区分。POST 失败不得透明改 GET；GET 只能作为单独、明确标注的候选探针。


## 代理

教程说明代理配置放在请求头映射的 `proxy` 键；MD3 `AnalyzeUrl` 源码也从 header map 提取 `proxy` 后移除。不要误写成未经支持的 UrlOption 字段。

## Cookie 与登录

根据目标能力使用 `enabledCookieJar`、`loginUrl`、`loginUi`、`loginCheckJs`、`java.getCookie()`。调试记录不写入敏感值；成品不要硬编码临时 Cookie、Authorization 或设备标识。

## WebView

仅在普通网络响应无法获得目标内容时使用。记录需要页面渲染、点击、脚本解密还是媒体请求。`webJs` 的返回语义按目标实现验证；空返回导致的循环风险必须测试。

## Rhino JS

- 优先 `var`、普通函数和索引循环。
- Java 重载参数明确传全，必要时 `String()` 强制类型。
- `java.ajaxAll()` 返回对象时按目标版本调用 `.body()`；不要照搬不同版本 API。
- 规则宿主期待列表时直接返回 JS Array / Java List；若最终将 `JSON.stringify(list)` 作为列表返回，可能触发类型转换异常。请求 body、header、日志或中间步骤可以合理使用序列化；`nextTocUrl` 中出现 stringify 只是启发式风险，静态扫描不能证明实际返回类型，须用目标引擎验证。
- 脚本末尾表达式与显式 `return` 的可用位置取决于规则包装方式；以目标源码/调试日志为准，不套用浏览器 JavaScript 的顶层 `return`。
- 捕获异常只用于调试，交付脚本应保留可诊断日志或明确失败，不要返回错误字符串冒充正文。
