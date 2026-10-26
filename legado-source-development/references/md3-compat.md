# HapeLee/legado-with-MD3 兼容基线

目标仓库：`HapeLee/legado-with-MD3`

- 已核对提交：`6dc297221a22e532354810fb2804592dd08e5a9d`（2026-08-26T17:14:51Z）
- 复核日期：2026-10-16（对照用户 APK + 上游 `main` 源码，见下「双源对账」）
- 目标 APK 更新后，应重新核对源码，不把本文件当永久事实。

## 双源对账（2026-10-16）

两条证据链互相独立，逐字段比对**无冲突**：

| 证据 | 来源 | 用途 |
|---|---|---|
| A. 目标 APK | 用户上传 `shared-ca814def.apk`，包名 `io.legato.kazusa`，revision `070ca1a9b2e4…` | 桩：dex 内 Room Schema 串 |
| B. 上游源码 | `HapeLee/legado-with-MD3@main`，`app/src/main/java/io/legado/app/data/entities/` | 桩：Kotlin data class |

- APK 时间上略早于 B 的当前 HEAD（上游 2026-10-14 仍有提交），但字段集合一致。
- **字段以 A 为准**（目标程序证据 > 源码）；B 用于读懂语义与备注。
- `BookSource.kt` 顶层 39 字段 + `BookInfoRule`/`TocRule`/`SearchRule`/`ExploreRule`/`ContentRule`/`ReviewRule` 已逐条核对。

### 字段表（实测，可直接抄）

- `ruleBookInfo`：`init` `name` `author` `intro` `kind` `lastChapter` `updateTime` `coverUrl` `tocUrl` `wordCount` `canReName` `downloadUrls` `relatedBooks`
- `ruleToc`：`preUpdateJs` `chapterList` `chapterName` `chapterUrl` `formatJs` `isVolume` `isVip` `isPay` `updateTime` `nextTocUrl`
- `ruleSearch`：`checkKeyWord` + 列表字段（`bookList` `name` `author` `intro` `kind` `lastChapter` `updateTime` `bookUrl` `coverUrl` `wordCount`）
- `ruleExplore`：同 `ruleSearch` 但**无** `checkKeyWord`
- `ruleContent`：`content` `subContent` `title` `nextContentUrl` `webJs` `sourceRegex` `replaceRegex` `imageStyle` `imageDecode` `payAction` `callBackJs`
- 顶层扩展（旧教程多未收录）：`jsLib` `enabledCookieJar` `concurrentRate` `coverDecodeJs` `variableComment` `respondTime` `exploreScreen` `ruleReview` `eventListener` `customButton` `homepageModules`

> ⚠️ `ruleBookInfo` 含 `updateTime`，但部分旧版本文档未列；以本表为准。
> ⚠️ `ruleExplore` **没有** `checkKeyWord`——写了也会被反序列化忽略。

## 证据范围

`BookSource.kt` 确认顶层含基础、登录、规则对象及 `eventListener`、`customButton`、`homepageModules` 等扩展；`bookSourceType` 支持 0 文本、1 音频、2 图片、3 文件、4 视频。

规则模型确认：

- `ruleSearch`：`checkKeyWord`、列表及书籍字段
- `ruleExplore`：列表及书籍字段
- `ruleBookInfo`：`init`、常规详情字段、`downloadUrls`、`relatedBooks`
- `ruleToc`：`preUpdateJs`、章节字段、`formatJs`、`isVolume`、`isPay`、分页
- `ruleContent`：`subContent`、`title`、`replaceRegex`、`imageStyle`、`imageDecode`、`payAction`、`callBackJs` 等
- `ruleReview`：段评字段；字段存在不代表全部 UI/业务已完成

### ★详情预处理字段真名 = `init`（2026-10-16 已定案，非「待复核」）

**结论**：`ruleBookInfo.init`，**不是** `bookInfoInit`。写 `bookInfoInit` 会**静默失效**。

**三重证据（互相独立，全部指向 `init`）**：

1. **目标 APK 实测**（最强）：用户上传的 `io.legato.kazusa` APK（revision `070ca1a9…`）
   的 `classes*.dex` 中，Room 生成的 Schema 串列出 `ruleBookInfo.init` 存在，
   而 `bookInfoInit` 出现次数为 **0**。
2. **MD3 上游源码**：`app/src/main/java/io/legado/app/data/entities/rule/BookInfoRule.kt`
   → `var init: String? = null`。
3. **喵公子文档第 6 节**把该字段标题写作「预处理规则(bookInfoInit)」，**标题错、正文对**：
   正文明确要求"js 的返回值需要是 json 对象，返回 `{a:…, b:…}`，书名规则填 `a`"——
   这正是 `init` 的行为语义。

> 若目标客户端为**旧版上游 Legado**（非 MD3 分支），同理以该版本的 `BookInfoRule.kt` 为准；
> 本文件只担保 MD3 分支与上述 APK。

**踩坑记录（值得引以为戒）**：`/var/minis/shared/legado/sources/` 的 `搬山人.json` 与
`蓝海搜书.json` 都带一个 **空的** `"bookInfoInit": ""` 键。空值不触发预处理，所以这两条源
**看起来"能用"**，于是错误字段名被"实测通过"掩盖了很久。教训：**空键不能作为字段名正确的证据**；
命名有疑问时，去 dex / 源码里搜字面量，不要靠"它能跑"反推。

**判别信号**：字段名写错的表现是「预处理完全不生效，且没有任何报错」。

**快速取字段表的办法（本机 aarch64 跑不了 aapt——它是 x86-64 ELF）**：

```sh
python3 - <<'EOF'
import zipfile
z = zipfile.ZipFile('目标.apk')
data = b''.join(z.read(n) for n in z.namelist() if n.endswith('.dex'))
i = data.find(b'ruleBookInfo.author')      # Room Schema 报错串的锚点
print(data[i-200:i+2200].decode('utf-8', 'replace'))
EOF
```

一次性吐出全部 `ruleXxx.字段` 真名，可与本文件字段表逐条对账。

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

## ★@js 宿主 API 边界（Rhino 1.8.1，2026-10-26 真机实测）

**沙箱 node 能跑 ≠ 真机能跑。** 本机 `js_eval.js` 走 node（V8，完整 ES + 浏览器子集），
真机走 Rhino 1.8.1（ES5，**无浏览器 API**）。以下函数在沙箱里有、在 Rhino 里没有，
一旦使用会抛 `ReferenceError: "xxx" 未定义`，整条链路直接崩：

| 不可用（浏览器/DOM 专属） | 替代写法 |
|---|---|
| `atob(s)` / `btoa(s)` | `java.base64Decode(s)` / `java.base64Encode(s)` |
| `fetch` / `XMLHttpRequest` | `java.ajax(url)` / `java.ajaxAll(urls)` |
| `Promise` / `async` / `await` | 同步写法；`java.ajax` 本身是同步的 |
| `document` / `window` / `location` / `navigator` | 用 `baseUrl`、`java.getString(rule)` |
| `setTimeout` / `setInterval` | 无（Rhino 宿主未注入） |
| `TextEncoder` / `TextDecoder` | 手写字节转换或 `java.strToBytes` |
| `crypto.subtle` / `CryptoJS` 全局名 | `java.hexDecodeToString` 等宿主方法，或自带实现 |

**也在 ES5 之外、Rhino 不保证可用**：`Array.prototype.includes`、`Object.assign`、
箭头函数、模板字符串、`let`/`const`、解构、可选链 `?.`。写 `@js` 一律按 ES5 写。

**本技能已确认可用的宿主对象**：`java.ajax`、`java.ajaxAll`、`java.getString`、
`java.getElement`、`java.base64Decode`、`java.base64Encode`、`java.hexDecode`、
`java.encodeURI`、`java.put`/`java.get`、`java.log`；变量 `result`、`src`、`baseUrl`、
`book`、`chapter`、`title`、`nextChapterUrl`。

**★纪律：写 `@js` 前先自问「这个函数 Rhino 1.8.1 有没有」。** 沙箱测试通过只证明逻辑对，
不证明能在真机执行；涉及 base64/网络/DOM 时，必须按上表改用宿主 API。


## 真机调试

MD3 Compose 调试页可能按模块自动处理 `++`/`--`。记录目标 APK 版本、完整输入、完整日志和输出语义。字段能反序列化、请求能成功、列表有数量，分别是不同验证阶段。
