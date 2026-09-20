# 测试、修复与交付

## 四层状态

1. `JSON_OK`：严格 JSON、类型、重复键通过。
2. `RULE_SAMPLE_OK`：规则在保存响应与目标同版本解析器中通过；版本不同只能标记 `RULE_APPROX_OK`。
3. `NETWORK_OK`：实时请求成功且结果语义正确。
4. `DEVICE_OK`：目标 APK 导入和调试日志确认。

不得跨级表述。前三层通过仍不能称目标 APK 可用。

## 统一 runner（参考聚阅沙箱）

具体书源优先使用一个入口完成静态、Gson、模块、断言、分页和传输报告：

```sh
cd /var/minis/shared/legado/sandbox
./run.py source.json --fixtures fixtures.json --all --transport --assert
```

输出 `report.json`，issues 分为 `STATIC/TRANSPORT/RULE/EMPTY/HARNESS`。`--assert` 下任一 issue 返回非零。调试探针可用于定位，但不能替代统一门禁。

## 同版本模块回归器

当前 JVM 回归器位于 `/var/minis/shared/legado/sandbox/`：

```sh
./run_source_module.sh source.json ruleSearch response.html BASE_URL 3
./run_source_module.sh source.json ruleBookInfo response.html BASE_URL 1
./run_source_module.sh source.json ruleToc response.html BASE_URL 3
./run_source_module.sh source.json ruleContent response.html BASE_URL 1
```

已支持 CSS、XPath、JSONPath、常用 Default（class/tag/id/text/children、单位置、数组索引/区间/排除），以及 Rhino `<js>`/`@js:` 的列表与字段链、相对 URL、常见 `##` 后处理和部分 `java` 宿主（select/selectOne/base64/md5/AES/encodeURI）。WebView、Cookie、Android 文件与完整网络宿主不在 JVM 中伪造，须进入实时网络或真机阶段；未实现调用会明确失败。若输出 `__ERROR__` 或进程非零，模块不通过。沙箱未实现的能力必须标为未验证，不可默认为成功。

## 书源回归矩阵

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
- 先确定阶段：JSON 读取、字段反序列化、请求、列表、字段、分页、JS/WebView。
- 修复后必须检查输出内容；“不再抛异常”不是通过。
- 若 App 收到的内容不明，本地 JSON 合法不能证明传输内容合法。

## 导入与传输验证

对 MD3 基线源码，书源管理页与编辑页均可解析对象或数组；因此 `MalformedJsonException` 不能武断归因于对象/数组形态。编辑页粘贴路径只是 `getClipText().trim()` 后直接交给 Gson，不会清理 Markdown 围栏或说明文字。

交付前执行：

```sh
python3 scripts/prepare_clipboard.py source.json -o source.clipboard.json
python3 scripts/copy_source.py source.json
```

前者生成无围栏、无说明文字的紧凑纯 JSON；后者再用目标 Gson 2.14 探针验证并直接写入 Android 剪贴板。禁止让用户从 Markdown 代码块手选复制整份书源。

## 版本与回滚

- 首版 `site.v1.json`，修订 `site.v2.json`；不覆盖已发送文件。
- 保存每版 SHA-256、变更点、验证层级。
- 用户原文件只读备份，修复在新文件进行。

## 发布报告模板

```text
目标：MD3 <版本/提交>
文件：site.vN.json
JSON：PASS
样本规则：PASS（解析器版本）
实时网络：PASS/未测
真机：PASS/用户待测/未测
分页：首/中/末页结果
已知限制：...
SHA-256：...
```
