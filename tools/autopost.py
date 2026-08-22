# -*- coding: utf-8 -*-
"""Автопубликация цитаты по расписанию.

Один запуск = один пост. Порядок: взять неиспользованную цитату,
отрисовать картинку, залить в хранилище, опубликовать, пометить цитату.

Защита от повторов трёхуровневая, потому что cron может сработать
дважды при перезапуске сервера или сдвиге времени:
1. Флаг used у цитаты — использованная не берётся заново.
2. Журнал post_log.json — по нему считается, сколько ушло за слот.
3. Файл блокировки — от двух одновременных запусков.
"""

import datetime
import json
import os
import re
import sys
import time
import urllib.error

import config
import github_upload
import meta_net
import render

API = "https://graph.instagram.com/v21.0"

LOG_PATH = os.path.join(config.ROOT, "post_log.json")
LOCK_PATH = os.path.join(config.ROOT, ".autopost.lock")
RUN_LOG = os.path.join(config.ROOT, "autopost.log")

LOCK_TTL = 900
NET_ATTEMPTS = 8
NET_DELAY = 20

CAPTION_TAGS = "#мотивация #цитаты #мысли #саморазвитие"


def log(message):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "%s  %s" % (stamp, message)
    print(line)
    try:
        with open(RUN_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        log("Файл %s повреждён, беру значение по умолчанию" % os.path.basename(path))
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def acquire_lock():
    if os.path.exists(LOCK_PATH):
        age = time.time() - os.path.getmtime(LOCK_PATH)
        if age < LOCK_TTL:
            log("Другой запуск работает (%d сек назад), выхожу" % age)
            return False
        log("Снимаю зависшую блокировку возрастом %d сек" % age)
        os.remove(LOCK_PATH)
    with open(LOCK_PATH, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    return True


def release_lock():
    if os.path.exists(LOCK_PATH):
        os.remove(LOCK_PATH)


def wait_for_network():
    for attempt in range(1, NET_ATTEMPTS + 1):
        try:
            meta_net.resolve("graph.instagram.com")
            return True
        except Exception:
            log("Сеть недоступна, попытка %d из %d" % (attempt, NET_ATTEMPTS))
            time.sleep(NET_DELAY)
    return False


def current_slot(now):
    """Ближайший слот из SLOTS, в который попадает текущий час."""
    slots = [int(s) for s in config.get("SLOTS", "6,18").split(",") if s.strip()]
    past = [s for s in slots if s <= now.hour]
    return max(past) if past else None


def already_posted(journal, day, slot):
    key = "%s_%02d" % (day.isoformat(), slot)
    return key in journal.get("posts", {})


def next_quote(data):
    for q in data["quotes"]:
        if not q.get("used"):
            return q
    return None


def publish(image_path, caption):
    """Заливает картинку и публикует. Возвращает media_id."""
    user_id = config.get("IG_USER_ID", required=True)
    token = config.get("IG_ACCESS_TOKEN", required=True)

    key = "motivation/%s" % os.path.basename(image_path)
    url = github_upload.upload(image_path, key)
    log("Загружено: %s" % url)

    container = meta_net.post("%s/%s/media" % (API, user_id), {
        "image_url": url,
        "caption": caption,
        "access_token": token,
    })
    creation_id = container["id"]

    for attempt in range(20):
        time.sleep(4)
        status = meta_net.get("%s/%s" % (API, creation_id),
                              {"fields": "status_code", "access_token": token})
        code = status.get("status_code")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError("Instagram не смог обработать картинку")
    else:
        raise RuntimeError("Контейнер не обработался за отведённое время")

    result = meta_net.post("%s/%s/media_publish" % (API, user_id), {
        "creation_id": creation_id,
        "access_token": token,
    })
    return result.get("id")


def main():
    dry = "--dry-run" in sys.argv
    force_slot = None
    for a in sys.argv:
        if a.startswith("--slot="):
            force_slot = int(a.split("=", 1)[1])

    log("=" * 55)
    log("Запуск" + (" (проверка, без отправки)" if dry else ""))

    if not acquire_lock():
        return 0

    try:
        now = datetime.datetime.now()
        slot = force_slot if force_slot is not None else current_slot(now)
        if slot is None:
            log("Сейчас %02d:%02d, ни один слот ещё не наступил" % (now.hour, now.minute))
            return 0

        journal = load_json(LOG_PATH, {"posts": {}})
        if already_posted(journal, now.date(), slot):
            log("Слот %02d:00 сегодня уже отработан, выхожу" % slot)
            return 0

        quotes = load_json(config.QUOTES, None)
        if not quotes:
            log("Не найдена база цитат: %s" % config.QUOTES)
            return 1

        quote = next_quote(quotes)
        if not quote:
            log("Все цитаты использованы, база требует пополнения")
            return 1

        theme = "белый" if (slot // 6) % 2 == 0 else "чёрный"
        log("Слот %02d:00, фон %s, цитата #%d: %s" % (slot, theme, quote["id"], quote["text"]))

        name = "%s_%02d.jpg" % (now.date().isoformat(), slot)
        image_path = os.path.join(config.OUTPUT, name)
        render.render(quote["text"], slot, image_path)
        log("Картинка отрисована: %s" % name)

        if dry:
            log("Проверка завершена, ничего не отправлено")
            return 0

        if not wait_for_network():
            log("Сеть недоступна, публикация отложена")
            return 1

        try:
            media_id = publish(image_path, "%s\n\n%s" % (quote["text"], CAPTION_TAGS))
        except (urllib.error.HTTPError, RuntimeError, KeyError) as e:
            body = e.read().decode()[:400] if hasattr(e, "read") else str(e)
            log("ОШИБКА публикации: %s" % body)
            return 1

        quote["used"] = True
        quote["used_at"] = now.isoformat(timespec="seconds")
        save_json(config.QUOTES, quotes)

        journal.setdefault("posts", {})["%s_%02d" % (now.date().isoformat(), slot)] = {
            "quote_id": quote["id"],
            "media_id": media_id,
            "at": now.isoformat(timespec="seconds"),
        }
        save_json(LOG_PATH, journal)

        left = sum(1 for q in quotes["quotes"] if not q.get("used"))
        log("Опубликовано, media_id %s. Осталось цитат: %d" % (media_id, left))
        if left < 10:
            log("ВНИМАНИЕ: цитаты заканчиваются, пополни quotes/quotes.json")
        return 0

    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
