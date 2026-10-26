# 2026-10-18 · wap.xbqg87.com（GBK 站）· 三个「规则看着对却全空」的脚本级盲区

站点：`https://wap.xbqg87.com`（新笔趣阁，响应 `charset=gbk`）。
成品：`/var/minis/shared/legado/sources/xbqg87.com.v1.json`；报告 `/var/minis/shared/legado/analysis/xbqg87/REPORT.md`。

## 一、症状与真因

三个页签依次报「全空」，逐条回原文核后，**没有一条是书源规则写错**，全是参考执行器与真机语义不一致：

| 现象 | 真因 | 修法 |
|---|---|---|
| 搜索/详情全乱码、字段全空 | `get()` 把 curl 的 stdout 硬按 `utf-8` 解码 | 新增 `pick_charset()`：URL 选项 `charset` → 响应头 `Content-Type` → HTML meta → utf-8 兜底；`-w` 增 `%{content_type}` 并在 bytes 上先切尾部标记 |
| `@css:#novelcontent@html` 恒 0 字 | `@html` 不是属性，旧代码走 `el.get('html')` → `None` | `css()` / `node_value()` 加 `attr == 'html'` 分支返回 `str(el)`（outerHTML） |
| `tocUrl: "{{baseUrl}}"` 请求成 `/5/5518`（丢尾斜杠）→ 404 | `expand_host_vars` 对 baseUrl 做了 `rstrip('/')`，而真机注入的是 bookUrl 原文 | 去掉 `rstrip('/')`，保留原文 |

★ 三者的共同点：**报错形态与「规则写错」完全一致**（空值、0 条、404），若不是先拿接口原始返回自证，会一路去改本来正确的选择器。

## 二、站点侧的三个坑（这次是真规则问题）

1. **目录全量内嵌详情页，尾部混入友情链**。`div.list_xm>ul` 里 5438 章之后接了 20 条外站链接，其中部分以 `.html` 结尾（`https://wap.sanjiange.com/book/301/301762/index.html`），所以 `[href$=".html"]` 过滤不干净，会把别站的书当成本书最后一章。
   → 改用 `li:has(a[href^="/"])`：站内章节目录一律以 `/` 开头的绝对路径，外链一律带协议。
2. **末页「下一页」会变成「下一章」**。正文分页是 `2_2.html`，但章节末页该位置的链接是 `3.html`，直接取 `li:last-child a@href` 必然串章。
   → `nextContentUrl: @css:.content_top a:contains(下一页)@href`：末页没有「下一页」这三个字，自然返回空、翻页停止。比 `@js` 判下划线更省事，也不依赖 `baseUrl`。
3. **`/sort/N.html` 是死链**。分类页自己给出的「下一页」是 `/sort/2.html`，实测 404（`/full/2.html`、`/paihang/allvisit_2.html` 正常）。发现页因此只走 `/paihang/` 六榜 + `/full/` 完本，共 7 入口。
   日/周/月点击榜页面为空榜（0 条），不入发现页。

## 三、可复用的判据

- **GBK/GB2312 站先看 `-w %{content_type}`**，再决定解码；不要用「中文变问号」去反推选择器。
- **属性选择器过滤外链优先用 `[href^="/"]`**，不要用后缀；外链可以长得和站内一模一样。
- **翻页规则用「链接文字」而不是「位置」**：站点的「下一页/下一章」文字差异是天然的边界信号。
- **`@html` 与 `@text` 的差别要单独验**：前者恒空时，正文页签会显示「取值 0 字」，看着像正文选择器挂了。

## 四、门禁

`validate_source.py --strict` PASS（0 错 0 警）；`test_debug_parser.py` 64/64；`sandbox_runner.py --all --assert` 参考层通过（JVM 缺席，未评 DEVICE_OK）；`e2e.py` 三本书 × 搜索/详情/目录/正文两页 ALL PASS。
