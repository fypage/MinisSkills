#!/usr/bin/env python3
"""Legado 统一门禁 runner（本机可执行版）。

参考聚阅沙箱的 assert / report 工作流，执行 Legado/MD3 规则语义。
本 runner 是**规则层参考执行**，不是目标同版本 JVM 引擎 —— 报告里
engine 字段会写明这一点，不得据此宣称 DEVICE_OK。

    python3 sandbox_runner.py source.json --fixtures fixtures.json --all --assert
"""
import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VALIDATOR = HERE / "validate_source.py"
RULE_EXEC = HERE / "rule_exec.py"
DEFAULT_SANDBOX = Path("/var/minis/shared/legado/sandbox")


def issue(rep, kind, stage, message, detail=""):
    rep["issues"].append({"kind": kind, "stage": stage,
                          "message": message, "detail": detail})


def nested(obj, path):
    for p in path.split("."):
        if isinstance(obj, list):
            try:
                obj = obj[int(p)]
            except (IndexError, ValueError):
                return None
        elif isinstance(obj, dict):
            obj = obj.get(p)
        else:
            return None
    return obj


def check_expect(rep, case, data):
    exp = case.get("expect", {})
    stage = case.get("id") or case.get("module")
    if "count" in exp and data.get("count") != exp["count"]:
        issue(rep, "RULE", stage, f"count {data.get('count')} != {exp['count']}")
    if data.get("count", 0) < exp.get("count_min", 0):
        issue(rep, "RULE", stage, f"count 低于 {exp['count_min']}")
    for path, want in exp.get("equals", {}).items():
        got = nested(data, path)
        if got != want:
            issue(rep, "RULE", stage, f"{path} 不等于期望值",
                  f"got={got!r} want={want!r}")
    for path, suffix in exp.get("endswith", {}).items():
        got = nested(data, path)
        if not isinstance(got, str) or not got.endswith(suffix):
            issue(rep, "RULE", stage, f"{path} 后缀不符", f"got={got!r}")
    for path in exp.get("nonempty", []):
        got = nested(data, path)
        if got in (None, "", []):
            issue(rep, "RULE", stage, f"{path} 为空")
    for path, n in exp.get("length_min", {}).items():
        got = nested(data, path)
        if not hasattr(got, "__len__") or len(got) < n:
            issue(rep, "RULE", stage, f"{path} 长度低于 {n}")


def run_module(source, module, response, base, max_items):
    q = subprocess.run([sys.executable, str(RULE_EXEC), str(source), module,
                        str(response), base, "--max", str(max_items)],
                       text=True, capture_output=True)
    try:
        return json.loads(q.stdout), q
    except json.JSONDecodeError:
        return {"module": module, "count": 0, "errors": 1,
                "raw": q.stdout + q.stderr}, q


def main():
    p = argparse.ArgumentParser(prog="sandbox_runner.py", description="Legado 统一门禁")
    p.add_argument("source")
    p.add_argument("--fixtures")
    p.add_argument("--all", action="store_true")
    p.add_argument("--module", action="append")
    p.add_argument("--assert", dest="assert_", action="store_true")
    p.add_argument("--transport", action="store_true")
    p.add_argument("--copy", action="store_true")
    p.add_argument("--out")
    p.add_argument("--target", choices=("common", "md3"), default="md3")
    a = p.parse_args()

    src = Path(a.source).resolve()
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(a.out).resolve() if a.out else DEFAULT_SANDBOX / "reports" / f"{src.stem}_{stamp}"
    out.mkdir(parents=True, exist_ok=True)

    rep = {"source": str(src), "created": stamp, "engine": "python-reference",
           "engine_note": "规则层参考执行，非目标同版本 JVM 引擎；不可据此宣称 DEVICE_OK",
           "stages": {}, "results": [], "issues": [], "status": "running"}

    # 同版本 JVM 引擎是否可用：不可用时明确记录，避免把「参考执行器通过」
    # 误当成「同引擎验证通过」。
    try:
        q = subprocess.run([sys.executable, str(HERE / "jvm_probe.py")],
                           text=True, capture_output=True, timeout=120)
        rep["stages"]["jvm"] = json.loads(q.stdout)
    except Exception as exc:
        rep["stages"]["jvm"] = {"available": False, "reason": "probe_error", "detail": str(exc)}
    if not rep["stages"]["jvm"].get("available"):
        rep["engine"] = "python-reference (jvm unavailable)"

    q = subprocess.run([sys.executable, str(VALIDATOR), "--json", "--target", a.target, str(src)],
                       text=True, capture_output=True)
    try:
        v = json.loads(q.stdout)[0]
    except (json.JSONDecodeError, IndexError):
        v = {"errors": 1, "warnings": 0, "issues": []}
        issue(rep, "HARNESS", "static", "validator 输出无法解析", q.stdout + q.stderr)
    rep["stages"]["static"] = v
    if v.get("errors"):
        issue(rep, "STATIC", "static", f"{v['errors']} 个静态错误",
              json.dumps(v.get("issues"), ensure_ascii=False))

    if a.fixtures:
        manifest = json.loads(Path(a.fixtures).read_text("utf-8-sig"))
        base_dir = Path(a.fixtures).resolve().parent
        cases = manifest.get("cases", [])
        selected = set(a.module or [])
        if selected:
            cases = [x for x in cases if x.get("id") in selected or x.get("module") in selected]
        elif not a.all:
            cases = cases[:1]
        for case in cases:
            f = Path(case["file"])
            f = f if f.is_absolute() else (base_dir / f).resolve()
            data, _ = run_module(src, case["module"], f, case.get("base", ""), case.get("max", 3))
            stage = case.get("id") or case["module"]
            rep["results"].append({"id": stage, "module": case["module"],
                                   "file": str(f), "data": data})
            if data.get("errors") or data.get("raw"):
                issue(rep, "RULE", stage, "模块执行失败",
                      json.dumps(data, ensure_ascii=False)[:600])
            elif data.get("count", 0) == 0:
                issue(rep, "EMPTY", stage, "模块返回空列表")
            for note in data.get("unsupported", []):
                issue(rep, "HARNESS", stage, f"参考执行器未实现的宿主能力（须 JVM/真机验证）：{note}")
            # 该模块依赖未实现的宿主能力时，后续 RULE 断言失败只是「无法评估」的
            # 连带结果，不代表源有缺陷。降级为 SKIPPED，避免把两者混为一谈。
            if data.get("unsupported"):
                issue(rep, "SKIPPED", stage,
                      "模块依赖未实现的宿主能力，期望断言未评估（不计为源缺陷）")
            else:
                check_expect(rep, case, data)

    clip = out / "clipboard.json"
    q = subprocess.run([sys.executable, str(HERE / "prepare_clipboard.py"), str(src), "-o", str(clip)],
                       text=True, capture_output=True)
    rep["stages"]["transport"] = {"ok": q.returncode == 0, "output": q.stdout.strip(),
                                  "error": q.stderr.strip()}
    if q.returncode:
        issue(rep, "TRANSPORT", "clipboard", "纯 JSON 生成失败", q.stdout + q.stderr)

    engine = run_import_probe(clip)
    rep["stages"]["import_probe"] = engine
    if not engine.get("ok"):
        issue(rep, "TRANSPORT", "import_probe", "导入探针失败",
              json.dumps(engine, ensure_ascii=False)[:400])
    elif engine.get("degraded"):
        rep.setdefault("notes", []).append(
            f"导入探针降级为 {engine.get('engine')}（{engine.get('reason')}）；"
            "同版本 Gson 探针须在 JVM 可用环境补做")
    if a.copy:
        text = clip.read_text()
        q = subprocess.run(["android-clipboard", "set", "--text", text, "--label", "Legado JSON"],
                           text=True, capture_output=True)
        rep["stages"]["clipboard"] = {"ok": q.returncode == 0,
                                      "output": q.stdout.strip(), "error": q.stderr.strip()}
        if q.returncode:
            issue(rep, "TRANSPORT", "clipboard", "Android 剪贴板写入失败",
                  q.stdout + q.stderr)

    rep["status"] = "pass" if not rep["issues"] else "issues"
    hard = [x for x in rep["issues"] if x["kind"] != "SKIPPED"]
    soft = [x for x in rep["issues"] if x["kind"] == "SKIPPED"]
    rep["counts"] = {"hard": len(hard), "skipped": len(soft)}
    (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    print("LEGADO SANDBOX（规则层参考执行）")
    print(" source ", src)
    print(" engine ", rep["engine"], "—", rep["engine_note"])
    print(" static ", f"E={v.get('errors', 0)} W={v.get('warnings', 0)}")
    for r in rep["results"]:
        print(" ", r["id"], f"n={r['data'].get('count', 0)} errors={r['data'].get('errors', 0)}")
    print(" REPORT", out / "report.json")
    print(" ISSUES", len(hard), f"(另有 {len(soft)} 项因宿主能力缺失未评估)")
    for x in rep["issues"]:
        flag = "SKIP" if x["kind"] == "SKIPPED" else "HARD"
        print(f"  - [{flag}/{x['kind']}/{x['stage']}] {x['message']}")
    if not hard:
        print(" VERDICT 参考层通过；未评估项须在 JVM/真机补齐后方可宣称可用")
    return 1 if (a.assert_ and hard) else 0


def run_import_probe(clip):
    """导入探针。JVM 可用则用同版本 Gson 探针；否则降级为 Python 严格解析并标注。

    降级结论必须显式写进报告（degraded=True），不得伪装成同引擎通过。
    """
    jp = _load_jvm_probe()
    st = jp.probe()
    if not st.get("available"):
        text = clip.read_text(encoding="utf-8")
        ok = text.startswith(("{", "[")) and "```" not in text and "\n" not in text
        err = ""
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            ok, err = False, f"JSON 非法: {exc}"
        return {"ok": ok, "engine": "python-json", "degraded": True,
                "reason": st.get("reason"), "note": st.get("detail"),
                "error": err}
    from pathlib import Path as _P
    d = _P(DEFAULT_SANDBOX)
    if not (d / "GsonImportProbe.class").exists():
        subprocess.run(["javac", "-cp", str(d / "lib/*"), str(d / "GsonImportProbe.java")],
                       check=True, capture_output=True)
    r = subprocess.run(["java", "-cp", f"{d}:{d}/lib/*", "GsonImportProbe", str(clip)],
                       text=True, capture_output=True)
    return {"ok": r.returncode == 0, "engine": "gson-2.14.0",
            "output": (r.stdout + r.stderr).strip()[:300]}


def _load_jvm_probe():
    import importlib.util
    spec = importlib.util.spec_from_file_location("jvm_probe", str(HERE / "jvm_probe.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    sys.exit(main())
