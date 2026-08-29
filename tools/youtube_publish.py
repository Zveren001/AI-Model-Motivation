# -*- coding: utf-8 -*-
"""Загрузка ролика на YouTube.

Вертикальное видео короче трёх минут YouTube сам считает Shorts, отдельного
эндпоинта для них нет — обычный videos.insert.

Файлы у нас в сотни килобайт, поэтому загрузка идёт одним multipart-запросом:
возобновляемая нужна от десятков мегабайт и сложнее без пользы.
"""

import json
import mimetypes
import os
import sys
import urllib.parse
import urllib.request

import config

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = ("https://www.googleapis.com/upload/youtube/v3/videos"
              "?uploadType=multipart&part=snippet,status")

CATEGORY_MOTIVATION = "22"
BOUNDARY = "----motivation-upload-boundary"


def configured():
    return bool(config.get("YT_REFRESH_TOKEN"))


def access_token():
    """Меняет долгоживущий refresh-токен на часовой ключ доступа."""
    data = urllib.parse.urlencode({
        "client_id": config.get("YT_CLIENT_ID", required=True),
        "client_secret": config.get("YT_CLIENT_SECRET", required=True),
        "refresh_token": config.get("YT_REFRESH_TOKEN", required=True),
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["access_token"]


def body(meta, video_path):
    """Тело multipart/related: сначала описание, следом сам файл."""
    kind = mimetypes.guess_type(video_path)[0] or "video/mp4"
    head = (
        "--%s\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n%s\r\n"
        "--%s\r\nContent-Type: %s\r\n\r\n"
        % (BOUNDARY, json.dumps(meta, ensure_ascii=False), BOUNDARY, kind)
    ).encode("utf-8")
    tail = ("\r\n--%s--\r\n" % BOUNDARY).encode()
    with open(video_path, "rb") as f:
        return head + f.read() + tail


def publish(video_path, title, description, tags=None, privacy="public"):
    """Заливает ролик и возвращает его id."""
    if not os.path.exists(video_path):
        sys.exit("Файл не найден: %s" % video_path)

    meta = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags or [],
            "categoryId": CATEGORY_MOTIVATION,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    req = urllib.request.Request(UPLOAD_URL, data=body(meta, video_path), method="POST")
    req.add_header("Authorization", "Bearer %s" % access_token())
    req.add_header("Content-Type", "multipart/related; boundary=%s" % BOUNDARY)

    with urllib.request.urlopen(req, timeout=600) as resp:
        result = json.loads(resp.read())

    return result.get("id"), result.get("status", {}).get("privacyStatus")


def main():
    if len(sys.argv) < 3:
        print("Использование: python youtube_publish.py <файл.mp4> \"текст цитаты\"")
        return 1

    path, text = sys.argv[1], sys.argv[2]
    video_id, privacy = publish(
        path, text, "%s\n\n#shorts #мотивация #цитаты" % text,
        tags=["мотивация", "цитаты", "shorts"])
    print("Загружено: https://youtube.com/watch?v=%s (%s)" % (video_id, privacy))
    return 0


if __name__ == "__main__":
    sys.exit(main())
