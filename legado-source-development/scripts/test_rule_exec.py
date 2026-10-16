#!/usr/bin/env python3
"""Legado 规则层参考执行器回归测试。

反证要求：每条测试都必须能在**还原缺陷后失败**。凡不能反证者一律不写。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXEC = HERE / "rule_exec.py"
FIX = Path("/var/minis/shared/legado/sandbox/fixtures")
SHUBAOC = Path("/var/minis/shared/legado/sources/cn.shubaoc.com.v2.json")
ANALYSIS = Path("/var/minis/shared/legado/analysis/shubaoc")


def run(source, module, response, base="", max_items=1, extra=()):
    q = subprocess.run(
        ["python3", str(EXEC), str(source), module, str(response), base,
         "--max", str(max_items), *extra],
        text=True, capture_output=True,
    )
    return q.returncode, q.stdout, q.stderr


def load(source, module, response, base="", max_items=1):
    rc, out, err = run(source, module, response, base, max_items)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise AssertionError(f"非 JSON 输出 rc={rc}\n{out}\n{err}")


def main():
    cases = []

    def check(name, cond, detail=""):
        cases.append((name, bool(cond), detail))

    # 1) CSS 列表根（无 @取值）必须返回元素，而非空
    d = load(SHUBAOC, "ruleSearch", ANALYSIS / "search.html",
             "https://cn.shubaoc.com/search/全球高武/")
    check("CSS 列表根无 @取值可建立节点上下文", d.get("count") == 1, str(d)[:200])
    check("搜索字段解析正确", d["rows"][0]["name"] == "全球高武", str(d["rows"][0]))

    # 2) 多命中字段必须用 \n 连接（Legado 语义），不得只取首项
    d = load(SHUBAOC, "ruleBookInfo", ANALYSIS / "book.html",
             "https://cn.shubaoc.com/novel/1103/")
    kind = d["rows"][0]["kind"]
    check("多命中 CSS 结果用 \\n 连接", kind == "网络名著\n全本", repr(kind))

    # 3) Jsoup 伪类 :matchesOwn 必须可用（真实站点的翻页规则依赖它）
    d = load(SHUBAOC, "ruleToc", ANALYSIS / "book.html",
             "https://cn.shubaoc.com/novel/1103/")
    check(":matchesOwn 选出下一页", d["rows"][0]["nextTocUrl"].endswith("/1103/1/"),
          d["rows"][0].get("nextTocUrl", ""))

    # 4) 末页必须停止（返回空），不得回绕或命中上一本
    d = load(SHUBAOC, "ruleToc", ANALYSIS / "book-last.html",
             "https://cn.shubaoc.com/novel/1103/14/")
    check("目录末页 nextTocUrl 为空", d["rows"][0]["nextTocUrl"] == "",
          repr(d["rows"][0]["nextTocUrl"]))
    check("目录末页不得命中「上一本」", "1100" not in d["rows"][0]["nextTocUrl"],
          repr(d["rows"][0]["nextTocUrl"]))

    # 5) 正文续页合并与停止
    d = load(SHUBAOC, "ruleContent", ANALYSIS / "chapter.html",
             "https://cn.shubaoc.com/novel/1103/5vuy9.html")
    check("正文首/中页 nextContentUrl 指向续页",
          d["rows"][0]["nextContentUrl"].endswith("5vuy9_2.html"),
          repr(d["rows"][0]["nextContentUrl"]))
    d = load(SHUBAOC, "ruleContent", ANALYSIS / "chapter2.html",
             "https://cn.shubaoc.com/novel/1103/5vuy9_2.html")
    check("正文末页 nextContentUrl 为空", d["rows"][0]["nextContentUrl"] == "",
          repr(d["rows"][0]["nextContentUrl"]))

    # 6) 字段缺少 @取值时，非列表字段必须报错而不是静默返回空
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        src = t / "s.json"
        src.write_text(json.dumps({
            "bookSourceUrl": "https://x.test", "bookSourceName": "X",
            "bookSourceType": 0,
            "ruleSearch": {"bookList": "@css:.item",
                           "name": "@css:.title"},
        }, ensure_ascii=False), encoding="utf-8")
        html = t / "x.html"
        html.write_text('<div class="item"><h2 class="title">T</h2></div>', encoding="utf-8")
        d = load(src, "ruleSearch", html, "https://x.test/")
        check("非列表字段缺 @取值应报错",
              d["errors"] >= 1 and "__ERROR__" in json.dumps(d, ensure_ascii=False),
              json.dumps(d, ensure_ascii=False)[:200])

    # 7) 相对 URL 必须解析为绝对
    d = load(SHUBAOC, "ruleExplore", ANALYSIS / "list-dushi2.html",
             "https://cn.shubaoc.com/list/dushi/2/")
    check("bookUrl 解析为绝对地址",
          d["rows"][0]["bookUrl"].startswith("https://cn.shubaoc.com/"),
          repr(d["rows"][0]["bookUrl"]))

    # 8) JS 规则必须显式报「未实现」，不得静默返回空冒充通过
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        src = t / "js.json"
        src.write_text(json.dumps({
            "bookSourceUrl": "https://x.test", "bookSourceName": "JS",
            "bookSourceType": 0,
            "ruleToc": {"chapterList": "<js>[]</js>", "chapterName": "@css:a@text"},
        }, ensure_ascii=False), encoding="utf-8")
        html = t / "x.html"
        html.write_text("<a href='/1'>c</a>", encoding="utf-8")
        d = load(src, "ruleToc", html, "https://x.test/")
        check("JS 规则显式标注未实现",
              d["errors"] >= 1 and "UnsupportedHost" in json.dumps(d, ensure_ascii=False),
              json.dumps(d, ensure_ascii=False)[:200])

    # 9) 伪类位于组合器链中段时，正则须校验其所在元素（h3），而非最终元素（li）
    SHX = Path("/var/minis/shared/legado/analysis/shuhuangxs.com/shu_44312.html")
    if SHX.exists():
        html = str(SHX)
        d = load(Path("/var/minis/shared/legado/sources/shuhuangxs.com.v2.json"),
                 "ruleToc", html, "https://www.shuhuangxs.com/shu/44312.html",
                 max_items=200)
        names = [r.get("chapterName", "") for r in d.get("rows", [])]
        check("伪类在链中段时校验 h3 而非 li", len(names) == 100,
              f"应 100 章，实得 {len(names)}")
        check("中段伪类首章正确", names and names[0].startswith("1归零"),
              repr(names[:1]))
        check("中段伪类不跨块误选", len(set(names)) == len(names),
              f"重复 {len(names) - len(set(names))} 条")

    # 11) Java 替换串语义（## 后半段）—— 2026-10-16 实测缺陷，须防回归
    #     ① `$0` 曾转成 `\0`（Python 读作 NUL 字节）→ 整条输出变成 '\x00'
    #     ② `$1` 原样透传 → Python 不认 Java 的 $1，输出字面量 "$1"
    #     ③ `[\s\S]` 曾丢反斜杠 → 变成 `[sS]`（在 Python 里碰巧等价，但语义已偏）
    sys.path.insert(0, str(HERE))
    import rule_exec as RE

    check("$0 转为 Python 的 \\g<0>（不得成为 NUL 字节）",
          RE._java_repl_to_python("$0") == "\\g<0>",
          repr(RE._java_repl_to_python("$0")))
    check("$1 转为 Python 的 \\1", RE._java_repl_to_python("$1") == "\\1",
          repr(RE._java_repl_to_python("$1")))
    check("$0 位于串中亦正确",
          RE._java_repl_to_python("a$0b") == "a\\g<0>b",
          repr(RE._java_repl_to_python("a$0b")))
    check("字符类内转义退化为字面量且不破坏字符类",
          RE._java_repl_to_python("[\\s\\S]*") == "[sS]*",
          repr(RE._java_repl_to_python("[\\s\\S]*")))
    check("Java 未知转义退化为字面量（对齐 runCatching 兜底）",
          RE._java_repl_to_python("\\s") == "s",
          repr(RE._java_repl_to_python("\\s")))

    # 端到端：捕获组提取作者/字数（真实站点形态）
    det = Path("/tmp/live_detail.html")
    if det.exists():
        html = det.read_text(encoding="utf-8")
        src = Path("/var/minis/shared/legado/sources/疯情书库.json")
        if src.exists():
            d = json.loads(src.read_text(encoding="utf-8"))
            g = d["ruleBookInfo"]
            a = RE.eval_rule(g["author"], html, "https://aabook.net/m/book-44.html")
            w = RE.eval_rule(g["wordCount"], html, "https://aabook.net/m/book-44.html")
            check("捕获组提取作者", a and a[0].strip() == "韩柏", repr(a))
            check("捕获组提取字数", w and w[0].strip() == "198822", repr(w))

    # 12) `##` 段数语义 —— 对齐 AnalyzeRule.SourceRule.makeUpRule
    #     rule##match##replace；出现第 4 段（索引>2）即 replaceFirst=true
    check("## 两段=普通替换",
          RE.strip_post("@css:p@text##a##b") == ("@css:p@text", "a", "b", False),
          str(RE.strip_post("@css:p@text##a##b")))
    check("## 四段=replaceFirst（不是 ### 后缀）",
          RE.strip_post("@css:p@text##a##b##")[3] is True,
          str(RE.strip_post("@css:p@text##a##b##")))
    check("## 三段仍为普通替换",
          RE.strip_post("@css:p@text##a##b##x")[3] is True,
          str(RE.strip_post("@css:p@text##a##b##x")))

    # 10) 真实源不因门禁而退化：书包网全橙
    man = FIX / "shubaoc-manifest.json"
    q = subprocess.run(
        ["python3", str(HERE / "sandbox_runner.py"), str(SHUBAOC),
         "--fixtures", str(man), "--all", "--assert"],
        text=True, capture_output=True,
    )
    check("书包网全量门禁 ISSUES=0", q.returncode == 0 and "ISSUES 0" in q.stdout,
          q.stdout[-300:])

    failed = [c for c in cases if not c[1]]
    for name, ok, detail in cases:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"   [{detail}]"))
    if failed:
        print(f"FAILED {len(failed)}/{len(cases)}")
        return 1
    print(f"PASS: rule_exec reference-executor regression suite ({len(cases)} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
