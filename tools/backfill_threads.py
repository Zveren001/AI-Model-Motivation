# -*- coding: utf-8 -*-
"""Дозаливка в Threads постов, которые вышли только в Instagram.

Нужен, когда Threads подключили позже Instagram: проходит по журналу,
находит записи без thread_id и публикует их по картинке, уже лежащей
в хранилище. Локальные файлы для этого не нужны — autopost их удаляет
сразу после публикации, а ссылка восстанавливается по ключу записи.

Запускать можно сколько угодно раз: уже дозалитые записи пропускаются.
"""

import json
import os
import sys
import time
import urllib.error

import autopost
import config
import threads_publish

PAUSE = 8


def image_url(key):
    """Ссылка на картинку в хранилище восстанавливается по ключу записи журнала."""
    owner = config.get("GITHUB_OWNER", required=True)
    repo = config.get("GITHUB_REPO", required=True)
    branch = config.get("GITHUB_BRANCH", "main")
    return "https://raw.githubusercontent.com/%s/%s/%s/motivation/%s.jpg" % (
        owner, repo, branch, key)


def quote_text(quotes, quote_id):
    for q in quotes["quotes"]:
        if q["id"] == quote_id:
            return q["text"]
    return None


def main():
    dry = "--dry-run" in sys.argv

    journal = autopost.load_json(autopost.LOG_PATH, {"posts": {}})
    quotes = autopost.load_json(config.QUOTES, None)
    if not quotes:
        sys.exit("Не найдена база цитат: %s" % config.QUOTES)

    pending = [(k, v) for k, v in sorted(journal.get("posts", {}).items())
               if not v.get("thread_id")]

    if not pending:
        print("Все записи журнала уже есть в Threads")
        return 0

    print("Без Threads: %d из %d" % (len(pending), len(journal["posts"])))

    for key, record in pending:
        text = quote_text(quotes, record["quote_id"])
        if not text:
            print("%s — цитата #%s не найдена, пропуск" % (key, record["quote_id"]))
            continue

        url = image_url(key)
        print()
        print("%s  цитата #%s: %s" % (key, record["quote_id"], text))

        if dry:
            print("   ушло бы: %s" % url)
            continue

        try:
            thread_id = threads_publish.publish(text, url, autopost.THREADS_TOPIC)
        except (urllib.error.HTTPError, RuntimeError, KeyError) as e:
            body = e.read().decode()[:300] if hasattr(e, "read") else str(e)
            print("   ОШИБКА: %s" % body)
            continue

        record["thread_id"] = thread_id
        autopost.save_json(autopost.LOG_PATH, journal)
        print("   Threads: %s" % thread_id)
        time.sleep(PAUSE)

    if dry:
        print()
        print("Проверка завершена, ничего не отправлено")
    return 0


if __name__ == "__main__":
    sys.exit(main())
