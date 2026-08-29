# -*- coding: utf-8 -*-
"""Автопубликация цитаты по расписанию.

Один запуск = один пост. Порядок: взять неиспользованную цитату, собрать
материал, залить в хранилище, опубликовать, пометить цитату.

Лента идёт циклом из четырёх: ролик белый, ролик чёрный, картинка белая,
картинка чёрная. Цвет меняется каждую публикацию, формат — через два. Час
публикации задаёт cron, минуты внутри часа добирает случайная пауза, поэтому
ключ --now нужен ручному запуску, чтобы не ждать её. Ключ --kind задаёт тип
принудительно, чередование дальше выправляется само.

Защита от повторов трёхуровневая, потому что cron может сработать
дважды при перезапуске сервера или сдвиге времени:
1. Флаг used у цитаты — использованная не берётся заново.
2. Журнал post_log.json — по нему считается, сколько ушло за слот.
3. Файл блокировки — от двух одновременных запусков.
"""

import datetime
import json
import os
import random
import re
import sys
import time
import urllib.error

import config
import github_upload
import meta_net
import reel
import render
import threads_publish

API = "https://graph.instagram.com/v21.0"

LOG_PATH = os.path.join(config.ROOT, "post_log.json")
LOCK_PATH = os.path.join(config.ROOT, ".autopost.lock")
RUN_LOG = os.path.join(config.ROOT, "autopost.log")

# Блокировка переживает разброс времени вместе с рендером ролика: полчаса сна
# плюс сборка видео легко перекрывают прежние пятнадцать минут.
LOCK_TTL = 3600
NET_ATTEMPTS = 8
NET_DELAY = 20

JITTER_MIN = 15 * 60
JITTER_MAX = 30 * 60

CAPTION_TAGS = "#мотивация #цитаты #мысли #саморазвитие"

# Threads принимает ровно одну тему на пост, хэштеги внутри текста там не работают
THREADS_TOPIC = "мотивация"

# Расписание задано по Москве, а сервер живёт по UTC. Брать datetime.now()
# нельзя: в 06:00 МСК скрипт увидел бы 03:00 и решил, что слот не наступил.
# Смещение задаётся числом, а не именем зоны: базы tzdata может не оказаться,
# а Москва с 2014 года стоит на UTC+3 без перехода на летнее время.
TZ = datetime.timezone(datetime.timedelta(hours=int(os.environ.get("UTC_OFFSET", "3"))))


def now_local():
    return datetime.datetime.now(TZ)


def log(message):
    stamp = now_local().strftime("%Y-%m-%d %H:%M:%S")
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


def drop_local(path):
    """Файл уже в хранилище — локальная копия не нужна ни после успеха, ни после сбоя.

    Без этого затяжной сбой публикации копил бы в output по файлу на каждый запуск.
    """
    try:
        os.remove(path)
    except OSError as e:
        log("Не удалось убрать локальный файл: %s" % e)


def current_slot(now):
    """Ближайший слот из SLOTS, в который попадает текущий час."""
    slots = [int(s) for s in config.get("SLOTS", "6,18").split(",") if s.strip()]
    past = [s for s in slots if s <= now.hour]
    return max(past) if past else None


def already_posted(journal, day, slot):
    key = "%s_%02d" % (day.isoformat(), slot)
    return key in journal.get("posts", {})


def next_index(journal):
    """Сквозной номер публикации.

    Считается по журналу, а не по часу: при любом наборе слотов
    нумерация остаётся строгой и после сбоя не сбивается.
    """
    return journal.get("counter", 0)


def last_post(journal):
    posts = journal.get("posts", {})
    if not posts:
        return None
    return max(posts.values(), key=lambda p: p.get("at", ""))


def next_quote(data):
    for q in data["quotes"]:
        if not q.get("used"):
            return q
    return None


def publish(fields, caption, attempts=20):
    """Публикует материал в Instagram по готовой ссылке. Возвращает media_id."""
    user_id = config.get("IG_USER_ID", required=True)
    token = config.get("IG_ACCESS_TOKEN", required=True)

    payload = dict(fields)
    payload["caption"] = caption
    payload["access_token"] = token

    container = meta_net.post("%s/%s/media" % (API, user_id), payload)
    creation_id = container["id"]

    for attempt in range(attempts):
        time.sleep(5)
        status = meta_net.get("%s/%s" % (API, creation_id),
                              {"fields": "status_code", "access_token": token})
        code = status.get("status_code")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError("Instagram не смог обработать материал")
    else:
        raise RuntimeError("Контейнер не обработался за отведённое время")

    result = meta_net.post("%s/%s/media_publish" % (API, user_id), {
        "creation_id": creation_id,
        "access_token": token,
    })
    return result.get("id")


def publish_image(url, caption):
    return publish({"image_url": url}, caption)


def publish_reel(url, caption):
    """Ролик обрабатывается дольше картинки, поэтому ждём вчетверо терпеливее."""
    return publish({"media_type": "REELS", "video_url": url,
                    "share_to_feed": "true"}, caption, attempts=48)


# Цикл ленты: цвет меняется каждую публикацию, формат идёт парами.
# Чередовать через один и цвет, и формат одновременно нельзя — периоды
# совпадут, и цвет намертво прилипнет к формату: все ролики станут чёрными,
# все картинки белыми. Приоритет отдан цвету, поэтому форматы идут по два.
CYCLE = [("reel", "white"), ("reel", "black"), ("image", "white"), ("image", "black")]


def next_cycle_pos(journal):
    """Позиция следующей публикации в цикле.

    Считается от последней записи журнала, а не от сквозного счётчика:
    ручная публикация и удаление поста из ленты сдвигают счёт, а позиция
    в цикле должна следовать за тем, что зритель видит в ленте на самом деле.
    """
    last = last_post(journal)
    if last is None or "cycle" not in last:
        return 0
    return (last["cycle"] + 1) % len(CYCLE)


def number_of_kind(journal, kind):
    """Порядковый номер внутри своего типа — по нему идёт эффект ролика.

    Считается по журналу, а не делением сквозного счётчика: ручной запуск
    с принудительным типом сбил бы деление, и ролик повторил бы эффект
    дважды подряд. Записи без пометки типа — картинки, они старше пометки.
    """
    return sum(1 for p in journal.get("posts", {}).values()
               if p.get("kind", "image") == kind)


def sleep_jitter():
    """Разброс перед публикацией, чтобы посты не выходили секунда в секунду.

    Час задаёт cron, минуты внутри часа — эта пауза: ровное расписание
    читается как автопостинг и самой площадкой, и живым читателем.
    """
    delay = random.randint(JITTER_MIN, JITTER_MAX)
    log("Разброс: пауза %d мин %d сек" % (delay // 60, delay % 60))
    time.sleep(delay)


def main():
    dry = "--dry-run" in sys.argv
    force_slot = None
    force_kind = None
    for a in sys.argv:
        if a.startswith("--slot="):
            force_slot = int(a.split("=", 1)[1])
        elif a.startswith("--kind="):
            force_kind = a.split("=", 1)[1]
            if force_kind not in ("image", "reel"):
                sys.exit("Ключ --kind принимает image или reel")

    log("=" * 55)
    log("Запуск" + (" (проверка, без отправки)" if dry else ""))

    if not acquire_lock():
        return 0

    try:
        now = now_local()
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

        index = next_index(journal)
        pos = next_cycle_pos(journal)
        cycle_kind, cycle_theme = CYCLE[pos]
        kind = force_kind or cycle_kind
        number = number_of_kind(journal, kind)
        theme = "белый" if cycle_theme == "white" else "чёрный"
        log("Слот %02d:00, пост #%d, %s, фон %s, цитата #%d: %s"
            % (slot, index + 1, "ролик" if kind == "reel" else "картинка",
               theme, quote["id"], quote["text"]))

        if kind == "reel":
            name = "%s_%02d.mp4" % (now.date().isoformat(), slot)
            media_path = os.path.join(config.OUTPUT, name)
            _, effect, _ = reel.render(quote["text"], number, media_path,
                                       theme=cycle_theme)
            log("Ролик собран: %s, эффект %s" % (name, effect))
        else:
            name = "%s_%02d.jpg" % (now.date().isoformat(), slot)
            media_path = os.path.join(config.OUTPUT, name)
            render.render(quote["text"], 0 if cycle_theme == "white" else 1, media_path)
            log("Картинка отрисована: %s" % name)

        if dry:
            log("Проверка завершена, ничего не отправлено")
            return 0

        if "--now" not in sys.argv:
            sleep_jitter()

        if not wait_for_network():
            log("Сеть недоступна, публикация отложена")
            return 1

        key = "motivation/%s" % os.path.basename(media_path)
        media_url = github_upload.upload(media_path, key)
        log("Загружено: %s" % media_url)

        caption = "%s\n\n%s" % (quote["text"], CAPTION_TAGS)
        try:
            if kind == "reel":
                media_id = publish_reel(media_url, caption)
            else:
                media_id = publish_image(media_url, caption)
        except (urllib.error.HTTPError, RuntimeError, KeyError) as e:
            body = e.read().decode()[:400] if hasattr(e, "read") else str(e)
            log("ОШИБКА публикации: %s" % body)
            drop_local(media_path)
            return 1

        thread_id = None
        if kind == "image" and config.get("THREADS_ACCESS_TOKEN"):
            try:
                thread_id = threads_publish.publish(quote["text"], media_url, THREADS_TOPIC)
                log("Threads: опубликовано, id %s" % thread_id)
            except (urllib.error.HTTPError, RuntimeError, KeyError) as e:
                body = e.read().decode()[:400] if hasattr(e, "read") else str(e)
                log("Threads не принял пост: %s" % body)

        quote["used"] = True
        quote["used_at"] = now.isoformat(timespec="seconds")
        save_json(config.QUOTES, quotes)

        journal.setdefault("posts", {})["%s_%02d" % (now.date().isoformat(), slot)] = {
            "quote_id": quote["id"],
            "media_id": media_id,
            "thread_id": thread_id,
            "index": index,
            "kind": kind,
            "cycle": pos,
            "theme": theme,
            "at": now.isoformat(timespec="seconds"),
        }
        journal["counter"] = index + 1
        save_json(LOG_PATH, journal)

        drop_local(media_path)

        left = sum(1 for q in quotes["quotes"] if not q.get("used"))
        log("Опубликовано, media_id %s. Осталось цитат: %d" % (media_id, left))
        if left < 10:
            log("ВНИМАНИЕ: цитаты заканчиваются, пополни quotes/quotes.json")
        return 0

    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
