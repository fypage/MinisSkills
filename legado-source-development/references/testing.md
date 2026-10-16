# 测试、修复与交付

## 四层状态

| 层级 | 含义 | 本机能到吗 |
|---|---|---|
| `JSON_OK` | 严格 JSON、类型、重复键通过 | ✅ 能 |
| `RULE_SAMPLE_OK` | 规则在保存响应上跑通，结果语义正确 | ⚠️ 分引擎，见下 |
| `NETWORK_OK` | 实时请求成功且结果正确 | 需网络与站点可达 |
| `DEVICE_OK` | 目标 APK 导入 + 调试日志确认 | ❌ 只能真机 |

**不得跨级表述。** 前三层通过仍不能称目标 APK 可用。

## ★引擎现状（2026-10-16 实测，务必先读）

**沙箱内 JVM 不可用。** HotSpot 启动即失败：

```
Error occurred during initialization of VM
Failed to mark memory page as executable - check if grsecurity/PaX is enabled
```

Linux 5.15 / aarch64 / PRoot 环境禁止可执行内存页，`java`（21）、`javac` 全部作废，
`-Xint`、`-XX:-UsePerfData` 等参数均无效。**因此 JVM 版探针（`GsonImportProbe`、
`SourceModuleProbe`、`run_source_module.sh`）在本机一律跑不起来**，它们的
`.class` 依赖需要独立补做。

由此产生两条必须遵守的纪律：

1. **规则层验证走 Python 参考执行器**（`scripts/rule_exec.py`），它不假装自己是
   同版本引擎，输出一律标注 `python-reference`。
2. **宿主能力缺失时报告必须写「未评估」，不能写「源有缺陷」。** 依赖 JS 的规则
   在当前环境无法判定，属取证不足，不属结论。

## 统一门禁（唯一入口）

```sh
cd /var/minis/skills/legado-source-development/scripts
python3 sandbox_runner.py <source.json> \
  --fixtures <fixtures.json> --all --transport --assert
```

| 参数 | 作用 |
|---|---|
| `--all` | 跑 fixtures 中全部用例 |
| `--transport` | 生成纯 JSON 传输副本并跑导入探针 |
| `--copy` | 额外写入 Android 剪贴板（交付用） |
| `--assert` | 存在**硬失败**时返回非零 |

报告落到 `/var/minis/shared/legado/sandbox/reports/<名>_<时间戳>/report.json`。
`issues[].kind` 取值：

| kind | 含义 | 影响退出码 |
|---|---|---|
| `STATIC` / `TRANSPORT` / `RULE` | 真问题 | ✅ 是 |
| `EMPTY` | 结构对但取值为空 | ✅ 是 |
| `HARNESS` | 参考执行器未实现的宿主能力，须 JVM/真机补做 | ✅ 是（提醒未完成） |
| `SKIPPED` | 因宿主缺失而**未评估**的期望断言（连带项） | ❌ 否 |

**关键区分**：`HARNESS` + `SKIPPED` 组合表示「这一块我们没资格下结论」，
既不能算通过，也不能当成源的缺陷。交付报告里必须如实写明。

## 参考执行器的能力边界（务必照实说）

`rule_exec.py` **已实现**：

- CSS：`@css:` 选择器、`@text` / `@ownText` / `@html` / `@属性`、`>` 子代、
  空格后代、`+` 相邻兄弟、`~` 通用兄弟、`||` / `&&` 连接
- Jsoup 伪类 `:matchesOwn(re)` / `:matches(re)`，**含伪类位于组合器链中段**的
  情形（如 `h3:matchesOwn(^章节列表)+.block-box ul.chapter-list>li`）
- XPath、JSONPath（需对应库）
- 多命中值按 Legado 语义用 `\n` 连接为单值（非取首项）
- 相对 URL 归一化；列表根（纯选择器、无 `@取值`）与普通字段的区分

**未实现**（会显式报 `unsupported`，不静默）：`<js>` / `@js:` 全部 JS 规则、
`@put` / `@get` 变量、WebView、Cookie、Android 文件与网络宿主。

## 旧 JVM 探针（本机不可用，保留备查）

若日后在 JVM 可用的机器上补做同引擎验证：

```sh
/var/minis/shared/legado/sandbox/run_source_module.sh source.json ruleToc response.html BASE_URL 3
```

历史输出样本见 `sandbox/reports/shubaoc-final|shubaoc-unified/report.json`，
当前参考执行器已用它们对齐过语义（含多值 `\n` 连接）。

## 回归套件

```sh
sh /var/minis/shared/legado/sandbox/run_all_tests.sh     # 全量
python3 scripts/test_rule_exec.py                        # 仅参考执行器
python3 scripts/test_debug_parser.py                     # 调试脚本解析器（64 项）
python3 scripts/jvm_probe.py                             # 引擎可用性自检
```

退出码：`0` 全过；`2` 有 SKIP（正常，说明 JVM 缺位）；`1` 有真失败。
`run_all_tests.sh` 会输出实际执行与跳过的条目，**不得只看末尾 PASS**。

## ★调试脚本自身的十个坑（2026-10-16 多源实测）

调试脚本一旦有缺陷，就会把「站点正常、规则正常」误报成规则错误。
以下每一条都曾在真实书源上复现：

| # | 症状 | 真因 |
|---|---|---|
| 1 | 搜索 0 条但无报错 | 首个 `@` 属 `@css:` 标记，`split_at=0` → 选择器切空 |
| 2 | author 变成整串原文 | `@text##正则##$1` 里取值与正则同处一个 `@` 之后，先切 `@` 会把正则整段丢掉 |
| 3 | 替换结果里出现字面 `$1` | JVM `Matcher.replaceAll` 的 `$1` 需换算成 Python 的 `\g<1>` |
| 4 | 整列字段为空 | `<js>result.replace(...)</js>` 未注入 `result`/`src` → ReferenceError 被吞成空串 |
| 5 | `@css:.t@text<js>...</js>` 恒空 | 把整条规则丢给 JS 执行器，没先按 CSS 取到元素值再当 `result` |
| 6 | `.t@text` 切不出选择器 | 后缀扫描起点写死 3，短规则被整段跳过 → `@text` 被当属性选择器 |
| 7 | 目录 0 条 | `tag.a.0@href` 简写未支持，字面 `tag.a.0` 抛 SelectorSyntaxError |
| 8 | 目录字段错位/为空 | 整页批量取 name/href 再 zip，未逐条目按节点取值 |
| 9 | 搜索词带中文报 400 | 关键词未 URL 编码（Legado 真机会自动编码） |
| 10 | HTTP 000、len=0 | 相对 URL 直接交给 curl（curl exit 6）；需补全成绝对地址 |

**共性**：全部表现为「规则像是写错了」，实际是工具错。
凡解析器/执行器返回空，都应区分「确实没匹配」与「自己解析错了」——
这也是脚本里 `⚠ 解析异常` / `⚠ 未支持` 两类提示存在的理由。

### 第二批：猫扑中文站实测（2026-10-16 下午）

换到一个**UA 敏感 + 目录内嵌 + 大目录**的站，又暴露 9 处。**这批比第一批更隐蔽**，
因为症状都像「站点/规则问题」：

| # | 症状 | 真因 |
|---|---|---|
| 11 | 全站 403，手测 curl 却 200 | 脚本 `get()` 硬编码 `-A curl/8.5.0`，**从不读 `bookSource.header`**。真机 Legado 会带 header，脚本不带 → 把「站点拒 UA」误判成规则错。已加 `set_header()` 并让 header 里的 UA 优先 |
| 12 | `tocUrl` 报 SelectorSyntaxError | `{{baseUrl}}` 未展开，被当 CSS 选择器送进解析器。已加 `expand_host_vars()`，`{{baseUrl}}`＝本书详情页地址 |
| 13 | `--book 3375` 拼不出地址 | toc 页签写死 `SITE + '/m/book-%s.html'`（aabook 专属形态）。已改为「优先 `--url`；否则用 `bookUrlPattern`；再否则以站点根请求并告警」 |
| 14 | 目录 0 条（容器选得到） | `eval_container` 返回的是 **字符串列表**（`css()` 结果），目录循环拿到 `str` 再取 `@text`/`@href` 必然全空且不报错。已让它返回**元素对象**（新增 `css_nodes()`） |
| 15 | 大目录（1596 章）跑到 OOM | `eval_field` 在节点取值**取到空就退回整页 `css()`** → 每章两次全页重解析，实测 194 秒后被 signal 9 杀掉。已去掉节点路径的整页回退（节点上取不到就是空，这是正确语义） |
| 16 | 目录容器 `:eq(n)` 不通 | `:eq` 是 jQuery 语义＝**在已选集上取第 n 个**，不是「选第 n 个父元素再往下取」。要按内容定位父块应用 `:has(.b:contains(XXX))` |
| 17 | `chapterName:"text"` 取空 | 裸值 `text`/`href` 不是合法取值后缀，**必须写 `@text`/`@href`**。这条是书源写错，不是脚本错——但脚本对此**不报错**，值得补提示 |
| 18 | `bookUrl` 拼成 `.../search.html, {"method":"POST"...` | 绝对化基准用了带 `,{...}` 选项的 `full`。已修正则基准为**站点根**（`SITE`） |
| 19 | `coverUrl` 显示相对路径 | 展示层未绝对化。已对 `bookUrl`/`coverUrl` 统一按站点根补全 |

**新增共性**：**「取到空」与「取错值」是两回事。** 第 14/17 条的可怕之处在于——
选择器明明选到 1596 条，取值全空，**界面一片安静**，只有把中间类型打出来才看见是 `str` 而非 `Tag`。
凡「容器选到了、字段却全空」，第一反应应当是**查容器返回的对象类型**。

### 第三批：猫扑中文站 · 真机反馈（2026-10-16 晚）

书源交付后用户导入真机实测，暴露 1 处**书源自身**的规则缺口。**这批不是工具缺陷，是规则缺陷**，
故记在本书源侧：

| # | 症状（真机） | 真因 | 修法 |
|---|---|---|---|
| 20 | **发现页/搜索页列表卡不显示封面，详情页却正常** | 条目由**两个并列 `li`** 组成：`li.tjimg`（含 `<img>`）+ `li.tjxs`（文字）。`bookList` 只框了 `li.tjxs`，**封面所在的 `li.tjimg` 根本没进容器**；`coverUrl` 又留空 `""` → 列表无图。详情页走 `.xsfm img@src`，另一条链路，故正常 | `bookList` 改框整条（`ul.xbk`），各字段选择器各自落到对应 li：`coverUrl: li.tjimg img@src`、`name: li.tjxs span.xsm a@text` |

**★通用教训（换站复现率高）**：
**列表卡无图而详情页有图 → 先查 `bookList` 是否只框住了文字块。**
搜书类站点的条目常写成「封面 `li` + 文字 `li` 并列」，`bookList` 必须框**整条**
（`ul`/`li` 的公共祖先），再让每个字段选择器各自定位到该字段所在的子块。
只框文字块时，`@href` 之类的相对取值仍能命中（所以书名/链接看着正常），
**唯独封面恒空**——症状极具迷惑性。

**另：源站封面本身可能就没图（不是规则问题）**。猫扑中文实测**发现页 30 条中 23 条 `src=""`**，
仅 7 条有封面。空 `src` 的 `img` 在 WebView 里**不会发起请求**，
连站内的 `onerror` 兜底图（ `/static/images/nocover.jpg`）也不会加载 → 界面只剩文字块。
**判读口径：列表无图时，先抓原始 HTML 看 `src` 是否空串，再动手改规则。**
实测有图的地址可取（`/uploads/images/113918s.jpg` → 200、57444 B、`image/jpeg`），
失效的才 404——图片链路本身没问题。

### 第四批：猫扑中文 · 正文分页（2026-10-16 晚，同一轮深查）

| # | 症状 | 真因 | 修法 |
|---|---|---|---|
| 21 | 长章节**只取到约 1/3 就断了**（如 2805 字的章只给出 1258 字） | 站点**章节正文有分页**：同章内页形如 `/{bookid}/{chapid}/N.html`，`#pb_next` 是下一页链接。书源 `nextContentUrl` 留空 → 只取第一页 | 设 `nextContentUrl` 跟 `#pb_next` |
| 22 | 直接跟 `#pb_next` 会**把整本书串成一篇** | **末页的 `#pb_next` 会变成「下一章」**（href 形如 `/{bookid}/{chapid}/`，另一章），不是「无下一页」——**终止条件不成立** | 见下「同章内页判据」 |
| 23 | 每页正文首部**重复**出现「阅读提示：…正常阅读！」 | 该提示是**每页各一份**。原规则 `##^阅读提示：.*?正常阅读！##` 的 `^` 锚定 + 隐式 count=1，**只清首次** | 去掉 `^`，改为 `##阅读提示：.*?正常阅读！##` 全局清除 |
| 24 | 部分页正文开头有**孤立 `>`** | 源站 HTML 残渣（`&gt;` 单独成行） | 取值后按行过滤空白与孤立 `>` |

**★同章内页判据（不依赖 `baseUrl`，重要）**：

```js
@js:var h=java.getString('#pb_next@href');
if(!h||h.indexOf('javascript')==0){result='';}
else if(/\/\d+\/\d+\/\d+\.html$/.test(h)){result=h;}
else{result='';}
```

**为什么不用 `baseUrl` 推章路径**：Legado 在 `nextContentUrl` 阶段，
`baseUrl` 往往是**书籍详情页地址**而非当前正文页地址，用它比对章路径必错。
**改判「href 是否带 `N.html` 尾缀」即足够**——同章内页必带，跨章链接必不带。
这一判据**不需要知道当前章是谁**，因而免疫 `baseUrl` 语义差异。

**验证方法**：用 `node` 直接跑判定函数做真值表（本机 `node` 可用），
比走 `exec_js_rule_node.py` 可靠得多——**该执行器对相当一部分 `@js` 返回空**，
连 `@js:result='HELLO';` 都是空串，**不能用来判定规则真假**（本机实测，见「已知限制」）。

## ★反爬镜像站：HTTP 200 也可能是错误页

站群常对错误请求返回广告页/空壳页而非错误码：**HTTP 200、长度正常**，
靠状态码与长度判成败必翻车。判定必须依赖**内容特征**（中文长文、且不含
`uicyAds`/`<script`/`window.location` 等壳页标记）。

反面案例：曾把 593 字节的广告页当成正文（长度看着合理、前缀也像），
并据此推出「token 无状态」这种假结论 —— **比对两个样本前，先确认这两个样本都是有效响应**。

## 书源回归矩阵（三站已实证）

| 站 | 搜索 | 发现 | 详情 | 目录 | 正文 | 备注 |
|---|---|---|---|---|---|---|
| aabook.net（疯情书库） | ✓ | ✓ | ✓ | ✓ | ✓ | `@js` + `java.ajax` 两跳取正文；UA 须 `curl/8.5.0` |
| 悠空网 / 无限小说网 / 蓝海搜书 / 小说巴士 / 幻梦轻小说 / 搬山人 | ✓ | ✓ | — | — | — | 多源实测 7/8 通过；书迷楼站点级 403 |
| **m.bookmaopu.com（猫扑中文）** | ✓30 | ✓30 | ✓ | ✓1596 | ✓ | **POST 搜索**（`/page/search.html`，字段 `searchkey`，中文须 URL 编码）；**须浏览器 UA**（`curl/8.5.0` 被 403）；目录内嵌书籍页，两块同名 `section.zxjz` 须用 `:has()` 取「全部章节」块；**条目为并列 `li.tjimg`+`li.tjxs`，`bookList` 须框整条**（见第三批 #20）；源站部分书无封面（`src=""`），非规则问题 |

| 模块 | 必查 |
|---|---|
| 导入 | 入口、对象/数组、字段不为空、覆盖行为 |
| 搜索 | 关键字、数量、首末项、无结果、分页 |
| 发现 | 分类、首末项、分页 |
| 详情 | 字段对齐、相对 URL、tocUrl 可请求 |
| 目录 | 首/中/末页、顺序、重复、停止条件 |
| 正文 | 首/续/末页、净化、图片、停止条件 |

## 报错处理

- 保存完整异常，不凭被截断的 Toast 猜根因。
- 先定位阶段：JSON 读取 → 字段反序列化 → 请求 → 列表 → 字段 → 分页 → JS/WebView。
- 修复后必须检查输出内容；「不再抛异常」不是通过。
- App 收到的内容不明时，本地 JSON 合法**不能**证明传输内容合法。

## 导入与传输验证

MD3 基线源码的书源管理页与编辑页均可解析对象或数组，因此
`MalformedJsonException` 不能武断归因于对象/数组形态。编辑页粘贴路径只是
`getClipText().trim()` 后交给 Gson，**不会清理 Markdown 围栏或说明文字**。

```sh
python3 scripts/prepare_clipboard.py source.json -o source.clipboard.json
python3 scripts/copy_source.py source.json      # 生成 + 探针 + 写剪贴板
```

`copy_source.py` 在 JVM 缺失时**降级为 Python 严格 JSON 校验**，并在输出中
标注 `"degraded": true`，绝不伪装成 Gson 通过。禁止让用户从 Markdown 代码块
手选复制整份书源。

## 版本与回滚

- 首版 `site.v1.json`，修订 `site.v2.json`；不覆盖已发送文件。
- 保存每版 SHA-256、变更点、验证层级。
- 用户原文件只读备份，修复在新文件进行。

## ★验证列表规则必须走模块级，不能单跑 `bookList`（2026-10-16 血证）

`bookList` / `chapterList` 是**容器规则**，本身不带 `@取值`。直接调 `eval_rule('@css:...')`
会抛「Default 规则缺少 @取值」——**这个报错会掩盖真正的容器错误**，而纠正它最省事的做法
往往是随手加个 `@text`，于是规则被改得面目全非却依然不工作。

**正确做法**：调 `eval_module(src, 'ruleExplore', html, url)`，它会以 `list_root=True`
建立节点上下文，返回 `count` 与逐项字段，**能真实反映「发现页有没有数据」**。

### ★`>` 子选择器是最隐蔽的空结果成因
实测本类站点：

| 选择器 | 匹配数 |
|---|---|
| `div.book-all-list>ul>li` | **0** |
| `div.book-all-list div.bd>ul>li` | **30** |

站点在容器与 `<ul>` 之间**多加了一层 `div.bd`**，`>` 要求直接子级，于是永远匹配不到。
**症状**：页头标题正常、下面空白、**无任何报错**（空列表不是异常）。

**判据**：凡「搜索页有数据、发现页没有」，先怀疑容器层级，用 BeautifulSoup
把 `>` 与空格两版都跑一遍对比（`soup.select()`），差 0 对 N 即是此因。
**不要凭对搜索页的印象推发现页**——两页的层级深度常常不同。

## 发布报告模板

```text
目标：MD3 <版本/提交>
文件：site.vN.json
JSON：PASS
样本规则：PASS（引擎：python-reference / 同版本 Rhino）
实时网络：PASS / 未测
真机：PASS / 用户待测 / 未测
分页：首/中/末页结果
未评估项：<HARNESS 列表，逐条写明须在何处补做>
已知限制：...
SHA-256：...
```

**报告里写在「未评估」一栏的内容，不得在任何地方表述为「已通过」。**
