#!/usr/bin/env python3
"""Small GitHub REST client for github-sync-helper.
Never prints the token. HTTP/API failures exit non-zero.
"""
import argparse, json, os, sys, urllib.error, urllib.parse, urllib.request

API = "https://api.github.com"

def request(method, path, payload=None):
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise SystemExit("missing env: GITHUB_TOKEN")
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "minis-github-sync-helper")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else {"status": r.status}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try: msg = json.loads(raw).get("message", raw[:300])
        except Exception: msg = raw[:300]
        raise SystemExit(f"GitHub API HTTP {e.code}: {msg}")
    except urllib.error.URLError as e:
        raise SystemExit(f"GitHub API network error: {e.reason}")

def repo_path(repo, suffix=""):
    if repo.count("/") != 1 or any(x in repo for x in ("..", "?", "#")):
        raise SystemExit("invalid --repo; expected owner/repo")
    return f"/repos/{repo}{suffix}"

def main():
    p=argparse.ArgumentParser()
    p.add_argument("method", choices=["GET","POST","PATCH","PUT","DELETE"])
    p.add_argument("path")
    p.add_argument("--data", default="")
    p.add_argument("--field", default="")
    a=p.parse_args()
    payload=json.loads(a.data) if a.data else None
    out=request(a.method, a.path, payload)
    if a.field:
        cur=out
        for key in a.field.split("."):
            cur=cur[int(key)] if isinstance(cur,list) else cur.get(key)
        if isinstance(cur,(dict,list)): print(json.dumps(cur,ensure_ascii=False))
        elif cur is not None: print(cur)
    else: print(json.dumps(out,ensure_ascii=False))
if __name__ == "__main__": main()
