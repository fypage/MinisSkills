#!/usr/bin/env python3
"""常驻 node 求值器：一次启动，逐条处理 @js 规则。

背景（2026-10-26 实测）：每条 @js 规则都 spawn 一次 node，冷启动 203 ms。
目录有 1001 章时约 200 秒，必然超时。本模块让 node 常驻，用 stdin/stdout
按行收发 JSON，把每条开销降到「执行本身」的量级。

用法（内部）：
    w = NodeWorker()
    out, log = w.eval(rule, base_url, subrules, binds)
    w.close()
"""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))

# node 端：循环读一行 JSON，执行 js_eval.js 的同一套逻辑，写回一行 JSON。
_DAEMON = r'''
const fs = require('fs');
const path = require('path');
const readline = require('readline');

// 复用 js_eval.js 的求值内核
const evPath = process.argv[2];
const core = require(evPath);

const rl = readline.createInterface({ input: process.stdin, terminal: false });
rl.on('line', (line) => {
  if (!line.trim()) return;
  let req;
  try { req = JSON.parse(line); } catch (e) {
    process.stdout.write(JSON.stringify({ id: null, out: '', log: [], err: 'BAD_JSON' }) + '\n');
    return;
  }
  let out = '', log = [], err = null;
  try {
    const r = core.evaluate(req.rule, req.baseUrl || '', req.subrules || {}, req.binds || {});
    out = r.out; log = r.log || []; err = r.err || null;
  } catch (e) {
    err = String(e && e.stack || e);
  }
  process.stdout.write(JSON.stringify({ id: req.id, out: out, log: log, err: err }) + '\n');
});
'''


class NodeWorker:
    """常驻 node 进程，逐条求值。失败自动降级为一次性调用。"""

    def __init__(self, js_eval_path: str | None = None):
        self._ev = js_eval_path or os.path.join(_HERE, 'js_eval.js')
        self._proc = None
        self._lock = threading.Lock()
        self._seq = 0
        self._daemon = '/tmp/_js_daemon.js'

    def _ensure(self):
        if self._proc is not None and self._proc.poll() is None:
            return True
        if not os.path.exists(self._ev):
            return False
        with open(self._daemon, 'w', encoding='utf-8') as f:
            f.write(_DAEMON)
        try:
            self._proc = subprocess.Popen(
                ['node', self._daemon, self._ev],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1,
            )
            return True
        except Exception:
            self._proc = None
            return False

    def eval(self, rule, base_url, subrules=None, binds=None, timeout=60.0):
        """返回 (out, log)。宿主不可用时退回一次性调用。"""
        if not self._ensure():
            return self._one_shot(rule, base_url, subrules, binds)
        with self._lock:
            self._seq += 1
            req = {'id': self._seq, 'rule': rule, 'baseUrl': base_url,
                   'subrules': dict(subrules or {}), 'binds': dict(binds or {})}
            try:
                self._proc.stdin.write(json.dumps(req, ensure_ascii=False) + '\n')
                self._proc.stdin.flush()
                out = self._proc.stdout.readline()
                if not out:
                    raise RuntimeError('node 常驻进程无响应')
                d = json.loads(out)
            except Exception:
                self.close()
                return self._one_shot(rule, base_url, subrules, binds)
        return d.get('out'), d.get('log', [])

    def _one_shot(self, rule, base_url, subrules=None, binds=None):
        """兜底：一次性 node 调用（与旧行为一致）。"""
        cfg = {'rule': rule, 'binds': dict(binds or {}), 'subrules': dict(subrules or {})}
        path = '/tmp/_rule_oneshot_%d.json' % os.getpid()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False)
        r = subprocess.run(['node', self._ev, path, base_url],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print('node stderr:', r.stderr[:400])
            return None, []
        try:
            d = json.loads(r.stdout)
        except Exception:
            print('无法解析 node 输出:', r.stdout[:300])
            return None, []
        return d.get('out'), d.get('log', [])

    def close(self):
        if self._proc is not None:
            try:
                self._proc.stdin.close()
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                pass
            self._proc = None


_shared: NodeWorker | None = None


def shared_worker() -> NodeWorker:
    """进程内共享一个常驻 worker。"""
    global _shared
    if _shared is None:
        _shared = NodeWorker()
    return _shared


def close_shared():
    global _shared
    if _shared is not None:
        _shared.close()
        _shared = None


# ★ 2026-10-26：进程退出时务必回收常驻 node，否则反复调用会累积孤儿进程，
#   最终被 PRoot 以 SIGKILL 收拾（表现为 "proot info: vpid 1: terminated with signal 9"）。
atexit.register(close_shared)
