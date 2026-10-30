# -*- coding: utf-8 -*-
"""SmartLect 部署后冒烟检查（只用标准库，Windows / Linux 都能跑）。

用法:
    python scripts/smoke_check.py [--base http://127.0.0.1:8080]

覆盖: 健康检查、管理员登录、用户列表权限、租客登录、智能匹配前置检查、
      未登录上传被拒、登录后上传、上传文件可下载、路径穿越被拒。
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid

FAILED = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (("  " + str(detail)) if detail else ""))
    if not ok:
        FAILED.append(name)


def call(base, method, path, token=None, body=None, raw=None, headers=None):
    url = base.rstrip("/") + path
    data = None
    hdrs = dict(headers or {})
    if raw is not None:
        data = raw
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json;charset=utf-8")
    if token:
        hdrs["token"] = token
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def parse(blob):
    try:
        return json.loads(blob.decode("utf-8"))
    except Exception:
        return {}


def multipart(field, filename, content, ctype):
    boundary = "----smartlect" + uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    base = args.base

    status, blob, _ = call(base, "GET", "/api/")
    body = parse(blob)
    check("health /api/", status == 200 and body.get("code") == "200", body)

    status, blob, _ = call(base, "POST", "/api/login", body={"username": "admin", "password": "admin"})
    body = parse(blob)
    admin = (body.get("data") or {}).get("token")
    check("admin login", body.get("code") == "200" and bool(admin), body.get("msg"))

    status, blob, _ = call(base, "GET", "/api/user/selectPage?page_num=1&page_size=1", token=admin)
    body = parse(blob)
    check("admin user list", body.get("code") == "200" and "list" in (body.get("data") or {}), body.get("msg"))

    status, blob, _ = call(base, "POST", "/api/login", body={"username": "member01", "password": "123456"})
    body = parse(blob)
    member = (body.get("data") or {}).get("token")
    check("member01 login", body.get("code") == "200" and bool(member), body.get("msg"))

    status, blob, _ = call(base, "GET", "/api/match/my", token=member)
    body = parse(blob)
    check("match page", body.get("code") == "200", body.get("msg"))

    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6360000002000154a24f5e0000000049454e44ae426082")
    raw, headers = multipart("file", "smoke.png", png, "image/png")
    status, blob, _ = call(base, "POST", "/api/files/upload", raw=raw, headers=headers)
    body = parse(blob)
    check("upload rejected without token", body.get("code") == "401", body.get("msg"))

    status, blob, _ = call(base, "POST", "/api/files/upload", token=member, raw=raw, headers=headers)
    body = parse(blob)
    url = body.get("data") or ""
    check("upload with token", body.get("code") == "200" and "/files/download/" in url, url)

    if url:
        path = url if url.startswith("/") else "/" + url.split("/", 3)[-1]
        status, blob, _ = call(base, "GET", path)
        check("download uploaded file", status == 200 and blob == png, status)
        name = url.rsplit("/", 1)[-1]
        status, blob, _ = call(base, "GET", "/api/files/download/..%2F..%2Fmain.py")
        check("download traversal rejected", status in (400, 404), status)
        call(base, "GET", "/api/files/download/" + name)

    print()
    if FAILED:
        print("FAILED:", ", ".join(FAILED))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
