# 技能自检、案例存档与版本表

## 一、技能自检清单（每次改动本技能后跑一遍）

```sh
cd /var/minis/skills/legado-source-development

# 1. 文档与脚本引用是否自洽（不得有断链）
rg -o 'scripts/[a-zA-Z0-9_.-]+\.py' SKILL.md references/*.md | sed 's/.*://' | sort -u | while read f; do
  [ -f "$f" ] && echo "  ok  $f" || echo "  MISSING $f"
done
rg -o 'references/[a-zA-Z0-9_.-]+\.md' SKILL.md references/*.md | sed 's/.*://' | sort -u | while read f; do
  [ -f "$f" ] && echo "  ok  $f" || echo "  MISSING $f"
done

# 2. 脚本语法
for f in scripts/*.py; do python3 -c "import ast,sys;ast.parse(open('$f',encoding='utf-8').read())" || echo "SYNTAX FAIL $f"; done

# 3. 自带回归（全绿才算可交付）
python3 scripts/test_rule_exec.py     # 参考执行器 25 例
python3 scripts/test_validator.py     # 校验器 14+28 例
python3 scripts/test_debug_parser.py  # 调试脚本解析器 64 例
```

**断链是硬伤**：导航表里写着、目录里没有，会让人以为「细则只是没读」。
其姊妹技能 `ju-yue-rule-development` 就吃过这个亏——`full-guide.md` 引用 50 份
`references/*.md`，实际一份都不存在。**引用即承诺，做不到就不要写。**

## 二、案例存档约定

| 类别 | 位置 | 说明 |
|---|---|---|
| 技能快照 | `/var/minis/shared/legado/backups/` | 每次大改打 tgz，含文件名与日期 |
| 书源成品 | `/var/minis/shared/legado/sources/` | 主文件 + 带版本后缀的历史版本 |
| 分析报告 | `/var/minis/shared/legado/analysis/<站点>/` | 一份 REPORT.md 收口 |
| 推送前备份 | `/var/minis/backups/minsiskills-legado-pre-push/` | 远端旧版留档，便于回滚 |
| **案例复盘** | `references/cases/<日期>-<站点>-<主题>.md` | 随技能走；只写方法与教训，**不放书源成品** |

**案例复盘的写法**：现象 → 初始误判 → 根因 → 正解 → **「为什么没测出来」** → 可复用清单。
最后一节是重点：**一个案例的价值在于它暴露了验证方法的什么缺口**，而不是它修好了哪个站。

**改前备份、改后复检**：脚本自报 OK 不算数，必须 `rg` 复检旧串归零
（曾发生批替换全部打印 OK 却未落盘）。

## 二之二、案例索引

| 案例 | 一句话结论 |
|---|---|
| [`cases/2026-10-18-xbqg87-gbk-charset.md`](cases/2026-10-18-xbqg87-gbk-charset.md) | **GBK 站的三重「假故障」**：脚本硬解 utf-8（全页乱码 → 选择器全空）、`@html` 被当属性名（正文恒 0 字）、`{{baseUrl}}` 被 `rstrip('/')`（`/5/5518/` → 404）。三处都长得像「规则写错」。另：目录尾部混入外站 `*.html` 友情链，`[href$=".html"]` 挡不住，要 `[href^="/"]`；正文末页「下一页」会变「下一章」，用 `a:contains(下一页)` 天然止步。 |
| [`cases/2026-10-bookmaopu-content-container.md`](cases/2026-10-bookmaopu-content-container.md) | **同一 `#nr1` 容器在不同书是两种结构**（33 个 `<p>` vs 43 个 `<br>`），`p@text` 会取空；容器级 `@text` 才通吃。★更重要：调试脚本**样本单一**（只验 `<p>` 型）+ **`textNodes` 静默降级**（改的规则从未被执行、却报通过）两个盲区叠加，导致问题一路「绿灯」。 |

## 三、仓库同步

技能发布仓库：`fypage/MinisSkills`，路径 `legado-source-development/`。

**★沙箱内 `github.com:443` 不通**（`git clone/push` 直接失败），
但 `api.github.com`、`codeload.github.com` 可达。故推送走 **Git Data API**：

```sh
python3 /var/minis/shared/legado/tools/push_skill_api.py   # 建 blob → tree → commit → 更新 ref
```

推送前必须先跑差异审计，确认**没有「远端独有、本地没有」的文件**，
否则整体覆盖会把远端的好东西删掉：

```sh
python3 /var/minis/shared/legado/tools/audit_skill_push.py
```

## 四、版本表

| 日期 | 变更 | 验证 |
|---|---|---|
| 2026-10-16 | 调试面板进技能：`debug_source.py`（站点无关五页签）、`exec_js_rule_node.py`（binds + `result`/`src` 注入）、`test_debug_parser.py`（64 项）；`testing.md` 增「十个坑」与「反爬镜像站」 | 64/64 + 30 PASS + 25 PASS + 校验 PASS |
| 2026-10-16（下午） | **猫扑中文站实测暴露 9 处并修复**：① 脚本读 `bookSource.header`（`set_header`，UA 优先）② `{{baseUrl}}` 展开（`expand_host_vars`）③ toc 页签去站点硬编码（改用 `--url`/`bookUrlPattern`）④ `eval_container` 返回**元素对象**而非字符串（新增 `css_nodes`）⑤ 去掉节点取值的整页回退（194s → 6.6s，消除 OOM）⑥ 目录容器统一走 `eval_container`（`:has()` 可用）⑦ `bookUrl`/`coverUrl` 绝对化基准改站点根 ⑧ 探索页补充绝对化 ⑨ 修正提示文案。书源成品 `sources/猫扑中文.json`（五页签全通） | 64/64 + 25 PASS + 14+28 PASS + 静态 PASS（0 错 0 警） |
| 2026-10-16（晚） | **真机反馈驱动的第 20 条（书源侧规则缺口）**：列表卡无图而详情页有图 → `bookList` 只框了文字块 `li.tjxs`，封面所在的 `li.tjimg` 未进容器。修法：`bookList` 框整条 `ul.xbk`，字段选择器各落到对应 li。`testing.md` 增「第三批」+ 回归矩阵补注；`book-source.md` 增「★`bookList` 必须框住整条」节（含 HTML 样例与判据）。另记「源站 `src=""` 无图 ≠ 规则问题」的判读口径 | 搜索 21/30 有封面、发现 8/30 有封面（其余为源站空 `src`）；静态 PASS；解析器 64/64 |
| 2026-10-18 | **GBK 站三处脚本缺陷（`wap.xbqg87.com` 实测暴露）**：① `get()` 硬按 utf-8 解码，GBK 站全页替换字符——选择器「全空」实为解码错；改为 `pick_charset()`（URL 选项 `charset` → 响应头 → HTML meta → utf-8）② `css()`/`node_value()` 把 `@html` 当属性名，`e.get('html')` 恒 None → 正文页签永远「取值 0 字」，与规则写错同形 ③ `expand_host_vars` 对 `{{baseUrl}}` 做 `rstrip('/')`，`/5/5518/` 这类以斜杠结尾的书籍页被剥成 `/5/5518` → 404。案例 `cases/2026-10-18-xbqg87-gbk-charset.md`；书源成品 `sources/xbqg87.com.v1.json` | 解析器 64/64；三本书端到端 ALL PASS；静态 PASS（0 错 0 警）；沙箱 `--all --assert` ISSUES 0 |
| 2026-10-16（晚·深查） | **第 21–24 条（书源侧）**：发现该站**正文有分页**——原 `nextContentUrl` 为空，长章只取到约 1/3（2805 字章实取 1258）。直接跟 `#pb_next` 又会把**整本书串成一篇**（末页该链接变「下一章」）。解法：`@js` 判「href 须带 `N.html` 尾缀」= 同章内页，**不依赖 `baseUrl`**（该阶段 `baseUrl` 语义不可靠）。另修：正文净化去掉 `^` 锚定（提示语**每页各一份**，原规则只清首次）；过滤源站孤立 `>` 残行。`testing.md` 增「第四批」 | node 真值表 6/6；链式取全文 5 页 5119 字、零残留；静态 PASS（0 错 0 警）；三套回归全绿（64 + 25 + 14/28） |
| 2026-10-26 | **v4.0.1：借上游 `Narylr350/book-source-creator-skill` 补静态铁律与失败分型**。① `validate_source.py` 新增 5 类检查：`;post=`/`;get=`、jQuery 伪类（仅 `:has/:visible/:hidden`）、`@css` 多 action 链、`ruleBookInfo.summary` 错名、**UA 完整性**；新增 `test_validator_lint.py`（17 项）② `debug_source.py` 新增失败分型 `code_of/classify_container/classify_content`，码表 `SELECTOR_EMPTY / HARNESS_UNSUPPORTED / TOC_EMPTY / TOC_SELECTOR_EMPTY / CONTENT_* / HTTP_BLOCKED`；新增 `test_debug_classify.py`（13 项）③ SKILL.md 补两节。**★最大教训：`:contains()` 不是错误**——首次照抄上游「Jsoup 不支持 jQuery 扩展」把它列为 error，导致 uukan/xbfdc/xhwx8 三份源误报 FAIL；参考执行器（soupsieve）实测支持，本技能 `rule-syntax.md` 亦早写明。**上游文档与本站实测冲突时，以本站实测为准。** | 解析器 64/64、validator 14+28、lint 17、分型 13、transport 全过；21 份成品源静态全 PASS |
| 2026-10-26（接入外部验证器） | **LA 主机跑上游 `legado-source-validator.jar` 作为第二意见**（JDK21，`/opt/legado-validator/`，systemd unit 已备但未 enable）。实测占用启动 59 MB、跑完一次验证 80 MB。★**该验证器三大缺陷（源码核实）**：① 不支持 `{{baseUrl}}` 与 `{{$.字段}}` 模板，替换成空串 ② 把 `@js:` 在部分位置当 CSS 选择器解析 ③ 相对路径以 `bookSourceUrl` 为基址，`https://x.com/m` + `/a.html` 会丢 `/m`。**结论：能发现形态问题，不能当「真机等价」裁决**；批量脚本把这类判为 `ENV_DEFECT`。★**出口 IP 地域拦截**：LA 访问 sushujuan/jcxs 返 520、xhwx8 返 451，本机正常，遇 4xx/5xx 须换本机复核 | 远程 OK 4 / ENV_DEFECT 7 / TRUST 2；本机复核全部正常 |

### 2026-10-26 书源修复实录（6 家）

| 书源 | 根因 | 修法 |
|---|---|---|
| `55kxs` | 站点改版，`search23.html` 已 404 | 改 `searchba.html`；`charset` 必须 UTF-8（GBK 参数导致搜不到） |
| `aabook` | ① 相对路径丢 `/m` 落到根站「疯情书库」② **正文接口对移动 UA 一律返广告页** | `searchUrl` 加 `m/` 前缀；UA 改桌面版；正文 id 改用 baseUrl 自身（页面首个 `read-` 是「上一章」链接）；`aabook_readfile` 切片偏移 +14→+15 |
| `jcxs` | 三处 `@js:` 被当 CSS 选择器 | 全改纯 CSS / 正则；分页 `@css:select.form-control option@value` |
| `uukan` | `@js:baseUrl.replace(...)`；正文 `@html` 混入标签 | `@css:dd a[href$='.html']:contains(全部章节)@href`；正文改 `@text` |
| `xhwx8` | 列表容器从 `ul.lis li` 改为 `dl > li`；`tocUrl` 指错位置 | 改容器；`tocUrl` → `<js>baseUrl</js>` |
| `sushujuan v1` | 旧 `class.` 写法；续页正则强制 `^https?://` 但站内是相对地址 | 同步 v5 规则；正则去前缀 |

未修复：`xbfdc.net` 整站已无搜索入口（站点改版，建议放弃）。


| 2026-10-26（v4.1.1） | **修复 `debug_source.py` 不接受数组形态**：Legado 标准导出是 `[{...}]`，脚本原来直接 `src.get()` → `AttributeError: 'list' object has no attribute 'get'`，界面上表现为「工具调用意外中断 / 卡住」。现支持单对象与数组双形态（数组取第 1 项，多项时打印警告），空数组与非法顶层给明确提示。另修 `utf-8` → `utf-8-sig`（带 BOM 的文件同样会崩）。**排查经验：工具连续报「意外中断」时，先看上一轮 tool result 的 traceback，往往是被中断掩盖的脚本异常。** | 解析器 64/64、分型 13、validator 14+28、lint 17、transport 全过；四种顶层形态（单对象/单元素数组/空数组/双元素数组）实跑验证 |

| 2026-10-26（v4.2.0） | **修复 `@js` 逐条 spawn node 导致的超时**：此前每条 `@js` 规则都启动一次 node，实测冷启动 **203 ms**；目录 1001 章（`chapterUrl` 为 `@js`）约需 **200 秒**，表现为「工具调用卡住 / 意外中断」。① `js_eval.js` 抽出 `evaluate()` 并加 `module.exports`，`require.main` 判空使 CLI 用法不变 ② 新增 `js_worker.py`：常驻 node 经 stdin/stdout 按行收发 JSON，单条降到 **0.6 ms**（约 340×）③ `exec_js_rule_node.run()` 改走共享 worker，崩溃/无响应自动降级为一次性调用。实测：`sudugu.cc` 992 章目录 **6.9 秒**（原约 200 秒）。 | 解析器 64/64、分型 13、validator 14+28、lint 17、transport 全过；容错实测（杀进程后自动降级并恢复、语法错误不致命） |

## 五、已知限制

- **同版本 JVM 引擎本机起不来**：PRoot/seccomp 禁止可执行内存页，
  OpenJDK 21 报 `Failed to mark memory page as executable`，`-Xint` 亦无效。
  故规则层上限为 **`RULE_REF_OK`**，`RULE_SAMPLE_OK` 需换允许 JIT 的宿主。
- 调试脚本只实现 **CSS 与 `@js`**；遇 JSONPath（`$.`）/ XPath（`//`）会明确报
  「未支持」，不硬解、不崩。
- `@js:` + `java.ajax` 在真机的行为**未经真机验证**，仅有等价 node 执行证据。
- **`exec_js_rule_node.py` 对相当一部分 `@js` 一律返回空串**（本机实测，
  连 `@js:result='HELLO';` 都是空），**不能用来判定规则真假**。
  JS 规则的正确验法：**把逻辑抽成纯函数，用本机 `node` 直接跑真值表**
  （不依赖 `java.*` 宿主对象的那部分逻辑，这样测得准）。
