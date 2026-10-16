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

**改前备份、改后复检**：脚本自报 OK 不算数，必须 `rg` 复检旧串归零
（曾发生批替换全部打印 OK 却未落盘）。

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
| 2026-10-16（晚·深查） | **第 21–24 条（书源侧）**：发现该站**正文有分页**——原 `nextContentUrl` 为空，长章只取到约 1/3（2805 字章实取 1258）。直接跟 `#pb_next` 又会把**整本书串成一篇**（末页该链接变「下一章」）。解法：`@js` 判「href 须带 `N.html` 尾缀」= 同章内页，**不依赖 `baseUrl`**（该阶段 `baseUrl` 语义不可靠）。另修：正文净化去掉 `^` 锚定（提示语**每页各一份**，原规则只清首次）；过滤源站孤立 `>` 残行。`testing.md` 增「第四批」 | node 真值表 6/6；链式取全文 5 页 5119 字、零残留；静态 PASS（0 错 0 警）；三套回归全绿（64 + 25 + 14/28） |

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
