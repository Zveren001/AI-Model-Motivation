# -*- coding: utf-8 -*-
"""Догрузка на YouTube роликов, вышедших только в Instagram.

Нужен после простоя: если загрузка падала, ролик всё равно опубликован
в Instagram и лежит в хранилище, а на канал не попал. Скрипт находит такие
по журналу, забирает файл из хранилища и заливает.

В журнал дописывается youtube_id, поэтому повторный запуск уже загруженное
не тронет и можно спокойно запускать хоть каждый день.
"""

import json
import os
import sys
import urllib.request

import config
import youtube_publish

LOG = os.path.join(config.ROOT, "post_log.json")
RAW = "https://raw.githubusercontent.com/%s/%s/%s/motivation/%s"

TAGS = "#shorts #мотивация #цитаты #саморазвитие"
KEYWORDS = ["мотивация", "цитаты", "саморазвитие", "shorts"]


def quote_text(quote_id):
    data = json.load(open(config.QUOTES, encoding="utf-8"))
    for q in data["quotes"]:
        if q["id"] == quote_id:
            return q["text"]
    return None


def pending(journal):
    """Ролики, у которых в журнале нет отметки о загрузке на YouTube."""
    return [(k, p) for k, p in sorted(journal["posts"].items())
            if p.get("kind") == "reel" and not p.get("youtube_id")]


def main():
    if not youtube_publish.configured():
        print("YT_REFRESH_TOKEN не задан, догружать нечем")
        return 1

    journal = json.load(open(LOG, encoding="utf-8"))
    owner = config.get("GITHUB_OWNER", required=True)
    repo = config.get("GITHUB_REPO", required=True)
    branch = config.get("GITHUB_BRANCH", "main")

    todo = pending(journal)
    if not todo:
        print("Всё загружено, догружать нечего")
        return 0

    dry = "--dry-run" in sys.argv
    print("Роликов без YouTube: %d" % len(todo))

    for key, post in todo:
        text = quote_text(post["quote_id"])
        if not text:
            print("  %s: цитата #%s не найдена" % (key, post.get("quote_id")))
            continue
        if dry:
            print("  %s: %s" % (key, text))
            continue

        name = "%s.mp4" % key
        local = os.path.join(config.OUTPUT, name)
        os.makedirs(config.OUTPUT, exist_ok=True)
        urllib.request.urlretrieve(RAW % (owner, repo, branch, name), local)

        video_id, privacy = youtube_publish.publish(
            local, text, text + "\n\n" + TAGS, tags=KEYWORDS)
        os.remove(local)

        post["youtube_id"] = video_id
        print("  %s -> https://youtube.com/watch?v=%s (%s)" % (key, video_id, privacy))

    if not dry:
        json.dump(journal, open(LOG, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
