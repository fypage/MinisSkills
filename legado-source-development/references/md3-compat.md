# HapeLee/legado-with-MD3 兼容基线

目标仓库：`HapeLee/legado-with-MD3`

- 已核对提交：`6dc297221a22e532354810fb2804592dd08e5a9d`
- 提交时间：2026-08-26T17:14:51Z
- 目标 APK 更新后，应重新核对源码，不把本文件当永久事实。

## 证据范围

`BookSource.kt` 确认顶层含基础、登录、规则对象及 `eventListener`、`customButton`、`homepageModules` 等扩展；`bookSourceType` 支持 0 文本、1 音频、2 图片、3 文件、4 视频。

规则模型确认：

- `ruleSearch`：`checkKeyWord`、列表及书籍字段
- `ruleExplore`：列表及书籍字段
- `ruleBookInfo`：`init`、常规详情字段、`downloadUrls`、`relatedBooks`
- `ruleToc`：`preUpdateJs`、章节字段、`formatJs`、`isVolume`、`isPay`、分页
- `ruleContent`：`subContent`、`title`、`replaceRegex`、`imageStyle`、`imageDecode`、`payAction`、`callBackJs` 等
- `ruleReview`：段评字段；字段存在不代表全部 UI/业务已完成

通用旧教程的详情预处理名是 `bookInfoInit`，此 MD3 基线模型使用 `init`。

## URL 选项

基线 `AnalyzeUrl.UrlOption` 支持：`method`（含 HEAD）、`charset`、`headers`、`body`、`origin`、`retry`、`type`、`webView`、`webJs`、`dnsIp`、`js`、`bodyJs`、`serverID`、`webViewDelayTime`。

## 导入契约（源码确认）

- 书源管理页 `BookSourceViewModel.parseImportSources()` 同时接受单对象和数组。
- 编辑页 `BookSourceEditViewModel.parseSource()` 同时接受单对象和数组；数组取第一项。
- 因此不能把 `MalformedJsonException` 无证据归因于“入口只接受对象/数组”。应检查 App 实际收到的全文、截断、包装、缓存、编码及异常位置。

## 解析器版本与已确认差异

基线依赖锁定：Jsoup `1.16.2`、JsoupXpath `2.5.5`、JsonPath `3.0.0`、Rhino `1.8.1`。近似测试若使用其他版本，必须标记版本偏差，不能算同引擎验证。

用户真机日志及同版本 JVM 探针均确认：JsoupXpath `2.5.5` 对含 `normalize-space()` 的规则抛出 `NoSuchFunctionException`。同一响应上已探针确认 `contains()`、`concat()`、`starts-with()`、`text()`、`position()`、`last()` 可执行，但这只证明相应表达式与样本，不代表实现全部 XPath 1.0。

制作 MD3 源优先 CSS/Default；必须使用 XPath 时，先用 `/var/minis/shared/legado/sandbox/EngineProbe.java` 的同版本引擎验证。

## 真机调试

MD3 Compose 调试页可能按模块自动处理 `++`/`--`。记录目标 APK 版本、完整输入、完整日志和输出语义。字段能反序列化、请求能成功、列表有数量，分别是不同验证阶段。
