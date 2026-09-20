# 书源字段与解析链路

## 核心对象

- 顶层：`bookSourceUrl`、`bookSourceName`、`bookSourceGroup`、`bookSourceType`、`header`、`searchUrl`、`exploreUrl`。
- 规则：`ruleSearch`、`ruleExplore`、`ruleBookInfo`、`ruleToc`、`ruleContent`。
- `bookSourceUrl` 是唯一标识；相同值导入时可能覆盖。

## 搜索 / 发现

列表字段：`bookList`、`name`、`author`、`kind`、`wordCount`、`lastChapter`、`intro`、`coverUrl`、`bookUrl`。

验证：尽量选择至少 2 项的样本检查名称和 URL 对齐，并补充单项及无结果场景；实际仅 0/1 项不应因此判失败。有分页时检查第 1/2 页不重复；无分页时可以没有 `{{page}}`，但须以响应行为确认。

发现地址常见：`名称::URL`，多项换行或 `&&`；也可能是样式 JSON。启用 `enabledExplore` 前必须实际验证至少一个分类。

## 详情

`ruleBookInfo` 常见：预处理、`name`、`author`、`kind`、`wordCount`、`lastChapter`、`intro`、`coverUrl`、`tocUrl`、`canReName`。

通用旧教程字段为 `bookInfoInit`；MD3 基线字段为 `init`。依据目标客户端选择，不以静态校验猜兼容。

验证 `tocUrl` 时必须继续请求该 URL 并得到正确目录，不能仅检查字符串非空。

## 目录

`chapterList` 建立节点上下文，随后解析 `chapterName`、`chapterUrl`、`isVip`、`updateTime`、`nextTocUrl`。

- 普通“下一页”分页：每一页只返回严格的后继页，末页为空。
- API/可枚举分页：`nextTocUrl` 可返回单 URL 或 URL/请求选项列表；返回类型以目标宿主为准，列表返回与中间序列化的区别见 `request-js.md`。
- `select` 下拉分页：常规值在 `option@value`；只有原始响应确有自定义 `value` 属性时才考虑 `select@value`。逐页跟随应只取严格后继，或返回按页序去重的后续页列表；一次枚举模式则按目标实现验证请求次数和合并顺序，不机械要求所有请求都排除前页。`option:not([selected])` 单独使用在中间页可能带入前页，但有额外上下文/后处理限制时不能仅凭该片段判错。
- 相对 URL 交由目标解析器或经验证的基址解析；不要手工拼接造成双斜杠、丢路径或跨域。

验证：
- 章节名与 URL 数量一致；
- 首尾章正确，顺序正确；
- 下一页只命中下一目录页；
- 最后一页停止；
- 合并分页后按 URL 去重检查，但不得用去重掩盖规则重复。

## 正文

`content`、`nextContentUrl`、`webJs`、`sourceRegex` 及目标分支扩展。

验证正文不是只看非空：检查首段、末段、正文长度、广告净化是否误删、图片 URL/headers、下一页合并与末页停止。`nextContentUrl` 只合并同一章节的续页；候选为“下一章/下章”或章节 ID 已变化时必须停止，不能用按钮文字模糊匹配把下一章正文串入当前章。

## 类型

通用教程主要覆盖 0 文本、1 音频；MD3 基线还支持 2 图片、3 文件、4 视频。类型编号和字段语义必须以目标客户端源码为准，不根据社区模板猜测。

| 类型 | 常见正文形态 | 重点验证 |
|---|---|---|
| 文本 | 纯文本或 HTML | 正文净化、分页、广告误删 |
| 音频 | 音频 URL 或媒体字段 | URL、请求头、播放能力 |
| 图片/漫画 | 图片 URL、图片标签或图片列表 | 图片顺序、请求头、懒加载、解密 |
| 文件 | 文件 URL 或下载字段 | 文件类型、下载/打开行为 |
| 视频 | 视频/HLS URL 或媒体字段 | 播放地址、清晰度、请求头 |

上表是分析维度，不是兼容承诺。每种扩展类型都要记录目标 APK/MD3 版本、规则字段、响应形态和实际验证层级；不能把“提取到 URL”直接称为“客户端可播放”。
