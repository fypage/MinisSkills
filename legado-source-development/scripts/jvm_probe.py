#!/usr/bin/env python3
"""探测同版本 JVM 引擎可用性。

PRoot 沙箱在 Android + seccomp 下禁止可执行内存页，HotSpot 无法启动。
本脚本把结论固化为可机读状态，供门禁与文档引用，避免每次靠肉眼判断。
"""
import json
import shutil
import subprocess
import sys

JAVA = shutil.which("java")
SANDBOX = "/var/minis/shared/legado/sandbox"
PAX_MARK = "Failed to mark memory page as executable"


def probe():
    if not JAVA:
        return {"available": False, "reason": "no_java", "detail": "PATH 中无 java（apk add openjdk21-jre）"}
    try:
        q = subprocess.run([JAVA, "-version"], text=True, capture_output=True, timeout=60)
    except Exception as exc:
        return {"available": False, "reason": "exec_error", "detail": str(exc)}
    msg = (q.stdout or "") + (q.stderr or "")
    if PAX_MARK in msg:
        return {
            "available": False,
            "reason": "no_exec_mem",
            "detail": "PRoot/Android seccomp 禁止可执行内存页，HotSpot 无法启动",
            "remedy": "改用 scripts/rule_exec.py（Python 参考执行器）做规则层验证；"
                      "同引擎级验证须在 x86 主机或真机上进行",
        }
    if q.returncode == 0:
        return {"available": True, "reason": "ok", "version": msg.strip().splitlines()[0]}
    return {"available": False, "reason": "unknown", "detail": msg[:400]}


def main():
    r = probe()
    r["jars"] = sorted(
        p.name for p in __import__("pathlib").Path(SANDBOX, "lib").glob("*.jar")
    ) if __import__("pathlib").Path(SANDBOX, "lib").is_dir() else []
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
