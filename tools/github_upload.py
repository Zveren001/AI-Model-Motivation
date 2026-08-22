# -*- coding: utf-8 -*-
"""Загрузка изображений в публичный репозиторий GitHub.

Instagram скачивает картинку по публичной ссылке, а GitHub раздаёт файлы
через raw.githubusercontent.com с HTTPS и без оплаты. Карта не нужна —
в отличие от Cloudflare R2 и остальных объектных хранилищ.
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request

import config

API = "https://api.github.com"


def _request(method, url, token, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": "Bearer %s" % token,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "nika-publisher",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = resp.read()
        return json.loads(body) if body else {}


def _existing_sha(owner, repo, path, branch, token):
    """GitHub требует sha при перезаписи существующего файла."""
    url = "%s/repos/%s/%s/contents/%s?ref=%s" % (API, owner, repo, path, branch)
    try:
        return _request("GET", url, token).get("sha")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def upload(local_path, key=None):
    """Заливает файл в репозиторий и возвращает публичную ссылку."""
    token = config.get("GITHUB_TOKEN", required=True)
    owner = config.get("GITHUB_OWNER", required=True)
    repo = config.get("GITHUB_REPO", required=True)
    branch = config.get("GITHUB_BRANCH", "main")

    if not os.path.exists(local_path):
        sys.exit("Файл не найден: %s" % local_path)

    key = (key or os.path.basename(local_path)).lstrip("/")

    with open(local_path, "rb") as f:
        content = base64.b64encode(f.read()).decode()

    payload = {
        "message": "upload %s" % key,
        "content": content,
        "branch": branch,
    }
    sha = _existing_sha(owner, repo, key, branch, token)
    if sha:
        payload["sha"] = sha

    url = "%s/repos/%s/%s/contents/%s" % (API, owner, repo, key)
    try:
        _request("PUT", url, token, payload)
    except urllib.error.HTTPError as e:
        sys.exit("GitHub вернул %s:\n%s" % (e.code, e.read().decode()[:600]))

    return "https://raw.githubusercontent.com/%s/%s/%s/%s" % (owner, repo, branch, key)


def main():
    if len(sys.argv) < 2:
        print("Использование: python github_upload.py <файл> [путь в репозитории]")
        return 1
    print(upload(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
