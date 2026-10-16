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

## ★反爬镜像站：HTTP 200 也可能是错误页

站群常对错误请求返回广告页/空壳页而非错误码：**HTTP 200、长度正常**，
靠状态码与长度判成败必翻车。判定必须依赖**内容特征**（中文长文、且不含
`uicyAds`/`<script`/`window.location` 等壳页标记）。

反面案例：曾把 593 字节的广告页当成正文（长度看着合理、前缀也像），
并据此推出「token 无状态」这种假结论 —— **比对两个样本前，先确认这两个样本都是有效响应**。

## 书源回归矩阵（两端 HTML 站已实证）

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
