# -*- coding: utf-8 -*-
"""Автопубликация по расписанию.

Один запуск = один пост. Порядок: выбрать цитату, собрать материал, залить
в хранилище, опубликовать, пометить цитату.

Тип публикации привязан к слоту: вечерние слоты из REEL_SLOTS отдают ролики,
остальные — картинки. Картинки идут по порядку базы, их фон чередуется
белый → чёрный от последней картинки. Ролик собирается из цитаты с развёрткой:
крючок, объяснение, совет и вопрос озвучиваются, слова идут на экране в ритм
речи поверх клипа из стока. Час публикации задаёт cron, минуты внутри часа
добирает случайная пауза, поэтому ключ --now нужен ручному запуску, чтобы
не ждать её. Ключ --kind задаёт тип принудительно.

Половина роликов заканчивается призывом писать в комментарии, половина —
только вопросом. Пока статистики мало, варианты чередуются поровну; дальше
доля следует за просмотрами из stats.json, который собирает youtube_stats.py.
Тема цитаты для ролика тоже выбирается по статистике: чаще из тем с лучшими
просмотрами, иногда наугад, чтобы не застрять.

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
import youtube_publish
import youtube_stats

API = "https://graph.instagram.com/v21.0"

LOG_PATH = os.path.join(config.ROOT, "post_log.json")
LOCK_PATH = os.path.join(config.ROOT, ".autopost.lock")
RUN_LOG = os.path.join(config.ROOT, "autopost.log")

# Блокировка переживает разброс времени вместе со сборкой ролика: полчаса сна,
# озвучка, скачивание клипа и кодирование легко перекрывают прежние пятнадцать минут.
LOCK_TTL = 3600
NET_ATTEMPTS = 8
NET_DELAY = 20

JITTER_MIN = 15 * 60
JITTER_MAX = 30 * 60

CAPTION_TAGS = "#мотивация #цитаты #мысли #саморазвитие"

# Вертикальное видео короче трёх минут YouTube сам относит к Shorts,
# хэштег в описании только помогает ему определиться быстрее
YOUTUBE_TAGS = "#shorts #мотивация #саморазвитие"
YOUTUBE_KEYWORDS = ["мотивация", "саморазвитие", "мысли", "психология", "shorts"]
FOOTAGE_CREDIT = "Видеоряд: pexels.com"

# Threads принимает ровно одну тему на пост, хэштеги внутри текста там не работают
THREADS_TOPIC = "мотивация"

# Доля роликов, где тема берётся наугад, а не из лучших по статистике,
# и сколько роликов каждого варианта нужно, прежде чем верить их средним
EXPLORE_SHARE = 0.3
MIN_SAMPLES = 8
TOP_TOPICS = 5

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


def hours(name, default):
    return [int(s) for s in config.get(name, default).split(",") if s.strip()]


def current_slot(now):
    """Ближайший слот из SLOTS, в который попадает текущий час."""
    past = [s for s in hours("SLOTS", "9,12,18,21") if s <= now.hour]
    return max(past) if past else None


def kind_by_slot(slot):
    return "reel" if slot in hours("REEL_SLOTS", "18,21") else "image"


def already_posted(journal, day, slot):
    key = "%s_%02d" % (day.isoformat(), slot)
    return key in journal.get("posts", {})


def next_index(journal):
    """Сквозной номер публикации.

    Считается по журналу, а не по часу: при любом наборе слотов
    нумерация остаётся строгой и после сбоя не сбивается.
    """
    return journal.get("counter", 0)


def posts_of(journal, kind):
    return [p for p in journal.get("posts", {}).values() if p.get("kind", "image") == kind]


def next_theme(journal):
    """Цвет картинки противоположен последней картинке.

    Считается от последней записи журнала, а не от счётчика: ручная
    публикация и удаление поста из ленты счёт сдвигают, а чередование
    должно следовать за тем, что зритель видит в ленте на самом деле.
    Ролики с видеорядом в чередовании не участвуют.
    """
    images = posts_of(journal, "image")
    if not images:
        return "white"
    last = max(images, key=lambda p: p.get("at", ""))
    return "black" if last.get("theme") == "белый" else "white"


def is_long(quote):
    return all(quote.get(k) for k in ("hook", "reasoning", "action", "question"))


def unused(quotes, long=None):
    pool = [q for q in quotes["quotes"] if not q.get("used")]
    if long is None:
        return pool
    return [q for q in pool if is_long(q) == long]


def next_quote(quotes):
    """Первая неиспользованная обычная цитата — для картинок порядок остаётся простым."""
    pool = unused(quotes, long=False)
    return pool[0] if pool else None


def share_by_stats(journal, stats, field, value):
    """Доля слотов для варианта поля по средним просмотрам роликов.

    Пока роликов каждого варианта меньше MIN_SAMPLES, доля ровно половина.
    Дальше она следует за результатом, но держится в пределах 25–75 %:
    проигравший вариант должен продолжать проверяться, иначе случайный
    провал первых роликов закрыл бы его навсегда.
    """
    scored = {}
    for post in posts_of(journal, "reel"):
        score = youtube_stats.video_score(stats, post.get("youtube_id"))
        if score is None or field not in post:
            continue
        scored.setdefault(post[field], []).append(score)

    mine = scored.get(value, [])
    others = [s for k, v in scored.items() if k != value for s in v]
    if len(mine) < MIN_SAMPLES or len(others) < MIN_SAMPLES:
        return 0.5
    a, b = sum(mine) / len(mine), sum(others) / len(others)
    if a + b == 0:
        return 0.5
    return min(0.75, max(0.25, a / (a + b)))


def pick_by_share(share, ordinal):
    """Ровно половина — чередование по порядку, иначе розыгрыш по доле."""
    if share == 0.5:
        return ordinal % 2 == 0
    return random.random() < share


def topic_scores(journal, stats, by_id):
    scores = {}
    for post in posts_of(journal, "reel"):
        score = youtube_stats.video_score(stats, post.get("youtube_id"))
        quote = by_id.get(post.get("quote_id"))
        if score is None or not quote:
            continue
        scores.setdefault(quote["topic"], []).append(score)
    return {t: sum(v) / len(v) for t, v in scores.items()}


def choose_reel_quote(pool, journal, stats, by_id):
    """Тема для ролика: чаще из лучших по просмотрам, иногда наугад.

    Лучшие темы разыгрываются пропорционально их среднему, а не берётся
    одна верхняя: с парой роликов на тему среднее ещё слишком шумное.
    """
    if not pool:
        return None, "нет цитат"
    scores = topic_scores(journal, stats, by_id)
    if not scores or random.random() < EXPLORE_SHARE:
        return random.choice(pool), "наугад"

    ranked = sorted(scores, key=scores.get, reverse=True)
    weighted = [(t, scores[t]) for t in ranked[:TOP_TOPICS]
                if any(q["topic"] == t for q in pool) and scores[t] > 0]
    if not weighted:
        return random.choice(pool), "наугад"

    roll = random.uniform(0, sum(w for _, w in weighted))
    for topic, weight in weighted:
        roll -= weight
        if roll <= 0:
            break
    return random.choice([q for q in pool if q["topic"] == topic]), "по статистике"


def choose_reel(quotes, journal, stats):
    """Цитата с развёрткой и вариант призыва для следующего ролика."""
    by_id = {q["id"]: q for q in quotes["quotes"]}
    reels = posts_of(journal, "reel")
    quote, how = choose_reel_quote(unused(quotes, long=True), journal, stats, by_id)
    cta = pick_by_share(share_by_stats(journal, stats, "cta", True), len(reels))
    return quote, cta, how


def caption_for(quote, long):
    parts = [quote["text"]]
    if long:
        parts = [quote["hook"], quote["reasoning"] + " " + quote["action"], quote["question"]]
    return "\n\n".join(parts + [CAPTION_TAGS])


def topic_tag(topic):
    return "#" + re.sub(r"[^\w]", "", topic)


def youtube_meta(quote):
    """Заголовок, описание и ключевые слова ролика для YouTube."""
    hook = quote["hook"].strip()
    joined = "%s %s" % (hook, quote["text"]) if hook[-1] in "?!" \
        else "%s. %s" % (hook.rstrip("."), quote["text"])
    title = joined if len(joined) <= 100 else hook
    description = "\n\n".join([
        quote["hook"], quote["reasoning"] + " " + quote["action"], quote["question"],
        FOOTAGE_CREDIT, "%s %s" % (YOUTUBE_TAGS, topic_tag(quote["topic"])),
    ])
    return title[:100], description, YOUTUBE_KEYWORDS + [quote["topic"]]


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

        kind = force_kind or kind_by_slot(slot)
        cta, how = None, "по порядку"
        if kind == "reel":
            quote, cta, how = choose_reel(quotes, journal, youtube_stats.load())
            if not quote:
                log("Цитаты с развёрткой закончились, нужна новая партия")
                return 1
        else:
            quote = next_quote(quotes)
            if not quote:
                log("Все цитаты использованы, база требует пополнения")
                return 1

        index = next_index(journal)
        theme_en = next_theme(journal) if kind == "image" else None
        theme = {"white": "белый", "black": "чёрный"}.get(theme_en)
        what = "ролик%s" % (" с призывом" if cta else "") if kind == "reel" else "картинка"
        log("Слот %02d:00, пост #%d, %s%s, тема «%s» %s, цитата #%d: %s"
            % (slot, index + 1, what, ", фон %s" % theme if theme else "",
               quote["topic"], how, quote["id"], quote["text"]))

        clip, duration = None, None
        if kind == "reel":
            name = "%s_%02d.mp4" % (now.date().isoformat(), slot)
            media_path = os.path.join(config.OUTPUT, name)
            try:
                _, clip, duration, _ = reel.render(quote, index, media_path, cta=cta, log=log)
            except RuntimeError as e:
                log("Ролик не собран, слот пропущен: %s" % e)
                return 1
            log("Ролик собран: %s, клип %s, %.1f с" % (name, clip, duration))
        else:
            name = "%s_%02d.jpg" % (now.date().isoformat(), slot)
            media_path = os.path.join(config.OUTPUT, name)
            render.render(quote["text"], 0 if theme_en == "white" else 1, media_path)
            log("Картинка отрисована: %s" % name)

        if dry:
            log("Проверка завершена, ничего не отправлено")
            return 0

        if "--now" not in sys.argv:
            sleep_jitter()

        if not wait_for_network():
            log("Сеть недоступна, публикация отложена")
            drop_local(media_path)
            return 1

        key = "motivation/%s" % os.path.basename(media_path)
        media_url = github_upload.upload(media_path, key)
        log("Загружено: %s" % media_url)

        caption = caption_for(quote, kind == "reel")
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

        youtube_id = None
        if kind == "reel" and youtube_publish.configured():
            title, description, keywords = youtube_meta(quote)
            try:
                youtube_id, privacy = youtube_publish.publish(
                    media_path, title, description, tags=keywords)
                log("YouTube: опубликовано, id %s, доступ %s" % (youtube_id, privacy))
            except (urllib.error.HTTPError, urllib.error.URLError, ValueError, KeyError) as e:
                detail = e.read().decode()[:400] if hasattr(e, "read") else str(e)
                log("YouTube не принял ролик: %s" % detail)

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
            "topic": quote["topic"],
            "media_id": media_id,
            "thread_id": thread_id,
            "index": index,
            "slot": slot,
            "kind": kind,
            "cta": cta,
            "clip": clip,
            "duration": duration,
            "youtube_id": youtube_id,
            "theme": theme,
            "at": now.isoformat(timespec="seconds"),
        }
        journal["counter"] = index + 1
        save_json(LOG_PATH, journal)

        drop_local(media_path)

        left = len(unused(quotes, long=False))
        left_long = len(unused(quotes, long=True))
        log("Опубликовано, media_id %s. Осталось цитат для картинок: %d, с развёрткой: %d"
            % (media_id, left, left_long))
        if left < 10:
            log("ВНИМАНИЕ: цитаты заканчиваются, пополни quotes/quotes.json")
        if left_long < 10:
            log("ВНИМАНИЕ: развёрнутые цитаты заканчиваются, нужна новая партия")
        return 0

    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
