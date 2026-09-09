# -*- coding: utf-8 -*-
"""Автопубликация по расписанию.

Один запуск = один пост. Порядок: выбрать цитату, собрать материал, залить
в хранилище, опубликовать, пометить цитату.

На YouTube в каждый из четырёх слотов уходит ролик, и формат фона идёт
ротацией: однотонный, сток, градиент, немой. За четыре дня каждый формат
успевает побывать в каждом слоте, поэтому время суток не смешивается
с форматом и сравнение остаётся честным.

Лента Instagram не меняется: в утренние слоты из IMAGE_SLOTS туда уходит
картинка на однотонном фоне, в остальные — тот же ролик, что и на YouTube.

Час публикации задаёт cron, минуты внутри часа добирает случайная пауза,
поэтому ключ --now нужен ручному запуску, чтобы не ждать её. Ключи --style,
--cta и --effect задают формат, призыв и эффект принудительно.

Тема ролика выбирается по статистике из stats.json, которую раз в сутки
собирает youtube_stats.py: чаще из тем с лучшими просмотрами, иногда наугад.
Тема, вышедшая в двух последних роликах, пропускается — иначе выбор
залипает на одной теме и лента выглядит как повтор. Призывы идут по кругу,
пока по каждому не наберётся статистика, дальше чаще выходит лучший.

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

import captions
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
YOUTUBE_TAGS = "#shorts #мотивация #цитаты"
YOUTUBE_KEYWORDS = ["мотивация", "цитаты", "саморазвитие", "мысли", "shorts"]
FOOTAGE_CREDIT = "Видеоряд: pexels.com"

# Threads принимает ровно одну тему на пост, хэштеги внутри текста там не работают
THREADS_TOPIC = "мотивация"

CTA_KINDS = ("comment", "subscribe", "like")
EFFECT_KINDS = captions.EFFECT_ORDER

# Доля роликов, где тема берётся наугад, а не из лучших по статистике;
# сколько роликов нужно на вариант, прежде чем верить его среднему;
# сколько последних тем под запретом
EXPLORE_SHARE = 0.3
MIN_SAMPLES = 6
TOP_TOPICS = 6
TOPIC_COOLDOWN = 2

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


def slots():
    return hours("SLOTS", "9,13,19,0")


def current_slot(now):
    """Ближайший слот из SLOTS, в который попадает текущий час."""
    past = [s for s in slots() if s <= now.hour]
    return max(past) if past else None


def instagram_image(slot):
    return slot in hours("IMAGE_SLOTS", "9,13")


def style_for(now, slot):
    """Формат фона по дате и месту слота в расписании.

    Ротация, а не статистика: пока форматов четыре и данных мало, важно
    чтобы каждый успел побывать в каждом слоте, иначе время суток
    и формат окажутся неразделимы.
    """
    order = slots()
    index = order.index(slot) if slot in order else 0
    return reel.STYLES[(now.date().toordinal() + index) % len(reel.STYLES)]


def already_posted(journal, day, slot):
    key = "%s_%02d" % (day.isoformat(), slot)
    return key in journal.get("posts", {})


def next_index(journal):
    """Сквозной номер публикации.

    Считается по журналу, а не по часу: при любом наборе слотов
    нумерация остаётся строгой и после сбоя не сбивается.
    """
    return journal.get("counter", 0)


def posts_of(journal, kind="reel"):
    return [p for p in journal.get("posts", {}).values() if p.get("kind", "image") == kind]


def next_theme(journal):
    """Цвет картинки противоположен последней картинке.

    Считается от последней записи журнала, а не от счётчика: ручная
    публикация и удаление поста из ленты счёт сдвигают, а чередование
    должно следовать за тем, что зритель видит в ленте на самом деле.
    Ролики с видеорядом в чередовании не участвуют.
    """
    images = [p for p in journal.get("posts", {}).values() if p.get("ig_kind") == "image"]
    if not images:
        return "white"
    last = max(images, key=lambda p: p.get("at", ""))
    return "black" if last.get("ig_theme") == "белый" else "white"


def unused(quotes):
    return [q for q in quotes["quotes"] if not q.get("used")]


def next_quote(quotes):
    """Первая неиспользованная цитата — для картинок порядок остаётся простым."""
    pool = unused(quotes)
    return pool[0] if pool else None


def scores_by(journal, stats, field, by_id=None):
    """Средние оценки роликов, сгруппированные по полю журнала или по теме цитаты."""
    groups = {}
    for post in posts_of(journal, "reel"):
        score = youtube_stats.video_score(stats, post.get("youtube_id"))
        if score is None:
            continue
        if field == "topic":
            quote = (by_id or {}).get(post.get("quote_id"))
            value = post.get("topic") or (quote or {}).get("topic")
        else:
            value = post.get(field)
        if value is not None:
            groups.setdefault(value, []).append(score)
    return groups


def weighted_choice(pairs):
    """Случайный элемент с вероятностью, пропорциональной весу."""
    roll = random.uniform(0, sum(w for _, w in pairs))
    for value, weight in pairs:
        roll -= weight
        if roll <= 0:
            return value
    return pairs[-1][0]


def recent_topics(journal, by_id):
    """Темы двух последних роликов — их следующий ролик пропускает."""
    reels = sorted(posts_of(journal, "reel"), key=lambda p: p.get("at", ""))
    out = set()
    for post in reels[-TOPIC_COOLDOWN:]:
        quote = by_id.get(post.get("quote_id"))
        topic = post.get("topic") or (quote or {}).get("topic")
        if topic:
            out.add(topic)
    return out


def choose_variant(journal, stats, field, kinds):
    """Вариант поля: по кругу, пока мало данных, дальше чаще лучший."""
    groups = scores_by(journal, stats, field)
    if any(len(groups.get(k, [])) < MIN_SAMPLES for k in kinds):
        return kinds[len(posts_of(journal, "reel")) % len(kinds)]
    return weighted_choice([(k, sum(groups[k]) / len(groups[k])) for k in kinds])


def choose_reel_quote(quotes, journal, stats):
    """Цитата для ролика: тема чаще из лучших по просмотрам, иногда наугад.

    Лучшие темы разыгрываются пропорционально их среднему, а не берётся
    одна верхняя: с парой роликов на тему среднее ещё слишком шумное.
    """
    by_id = {q["id"]: q for q in quotes["quotes"]}
    skip = recent_topics(journal, by_id)
    pool = [q for q in unused(quotes) if q["topic"] not in skip] or unused(quotes)
    if not pool:
        return None, "нет цитат"

    groups = scores_by(journal, stats, "topic", by_id)
    means = {t: sum(v) / len(v) for t, v in groups.items() if t not in skip}
    if not means or random.random() < EXPLORE_SHARE:
        return random.choice(pool), "наугад"

    ranked = sorted(means, key=means.get, reverse=True)[:TOP_TOPICS]
    weighted = [(t, means[t]) for t in ranked
                if means[t] > 0 and any(q["topic"] == t for q in pool)]
    if not weighted:
        return random.choice(pool), "наугад"

    topic = weighted_choice(weighted)
    return random.choice([q for q in pool if q["topic"] == topic]), "по статистике"


def caption_for(quote):
    return "%s\n\n%s" % (quote["text"], CAPTION_TAGS)


def topic_tag(topic):
    return "#" + re.sub(r"[^\w]", "", topic)


def youtube_meta(quote):
    """Заголовок, описание и ключевые слова ролика для YouTube."""
    description = "\n\n".join([quote["text"], FOOTAGE_CREDIT,
                               "%s %s" % (YOUTUBE_TAGS, topic_tag(quote["topic"]))])
    return quote["text"][:100], description, YOUTUBE_KEYWORDS + [quote["topic"]]


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
    force_style = None
    force_cta = None
    force_effect = None
    for a in sys.argv:
        if a.startswith("--slot="):
            force_slot = int(a.split("=", 1)[1])
        elif a.startswith("--style="):
            force_style = a.split("=", 1)[1]
            if force_style not in reel.STYLES:
                sys.exit("Ключ --style принимает %s" % ", ".join(reel.STYLES))
        elif a.startswith("--cta="):
            force_cta = a.split("=", 1)[1]
            if force_cta not in CTA_KINDS:
                sys.exit("Ключ --cta принимает %s" % ", ".join(CTA_KINDS))
        elif a.startswith("--effect="):
            force_effect = a.split("=", 1)[1]
            if force_effect not in EFFECT_KINDS:
                sys.exit("Ключ --effect принимает %s" % ", ".join(EFFECT_KINDS))

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

        stats = youtube_stats.load()
        quote, how = choose_reel_quote(quotes, journal, stats)
        if not quote:
            log("Все цитаты использованы, база требует пополнения")
            return 1

        style = force_style or style_for(now, slot)
        cta = force_cta or choose_variant(journal, stats, "cta", CTA_KINDS)
        effect = force_effect or choose_variant(journal, stats, "effect", EFFECT_KINDS)

        index = next_index(journal)
        day = now.date().isoformat()
        log("Слот %02d:00, пост #%d, формат %s, призыв %s, эффект %s, тема «%s» %s, цитата #%d: %s"
            % (slot, index + 1, style, cta, effect, quote["topic"], how,
               quote["id"], quote["text"]))

        media_path = os.path.join(config.OUTPUT, "%s_%02d.mp4" % (day, slot))
        try:
            _, source, duration, meta = reel.render(quote, index, media_path,
                                                    style=style, cta=cta,
                                                    effect=effect, log=log)
        except RuntimeError as e:
            log("Ролик не собран, слот пропущен: %s" % e)
            return 1
        log("Ролик собран: %s, %.1f с" % (source, duration))

        ig_kind = "image" if instagram_image(slot) else "reel"
        ig_theme_en = next_theme(journal) if ig_kind == "image" else None
        ig_theme = {"white": "белый", "black": "чёрный"}.get(ig_theme_en)
        ig_path = media_path
        if ig_kind == "image":
            ig_path = os.path.join(config.OUTPUT, "%s_%02d.jpg" % (day, slot))
            render.render(quote["text"], 0 if ig_theme_en == "white" else 1, ig_path)
            log("Картинка для Instagram отрисована, фон %s" % ig_theme)

        if dry:
            log("Проверка завершена, ничего не отправлено")
            return 0

        if "--now" not in sys.argv:
            sleep_jitter()

        if not wait_for_network():
            log("Сеть недоступна, публикация отложена")
            drop_local(media_path)
            if ig_path != media_path:
                drop_local(ig_path)
            return 1

        media_url = github_upload.upload(ig_path, "motivation/%s" % os.path.basename(ig_path))
        log("Загружено: %s" % media_url)

        caption = caption_for(quote)
        try:
            if ig_kind == "reel":
                media_id = publish_reel(media_url, caption)
            else:
                media_id = publish_image(media_url, caption)
        except (urllib.error.HTTPError, RuntimeError, KeyError) as e:
            body = e.read().decode()[:400] if hasattr(e, "read") else str(e)
            log("ОШИБКА публикации: %s" % body)
            drop_local(media_path)
            if ig_path != media_path:
                drop_local(ig_path)
            return 1

        youtube_id = None
        if youtube_publish.configured():
            title, description, keywords = youtube_meta(quote)
            try:
                youtube_id, privacy = youtube_publish.publish(
                    media_path, title, description, tags=keywords)
                log("YouTube: опубликовано, id %s, доступ %s" % (youtube_id, privacy))
            except (urllib.error.HTTPError, urllib.error.URLError, ValueError, KeyError) as e:
                detail = e.read().decode()[:400] if hasattr(e, "read") else str(e)
                log("YouTube не принял ролик: %s" % detail)

        thread_id = None
        if ig_kind == "image" and config.get("THREADS_ACCESS_TOKEN"):
            try:
                thread_id = threads_publish.publish(quote["text"], media_url, THREADS_TOPIC)
                log("Threads: опубликовано, id %s" % thread_id)
            except (urllib.error.HTTPError, RuntimeError, KeyError) as e:
                body = e.read().decode()[:400] if hasattr(e, "read") else str(e)
                log("Threads не принял пост: %s" % body)

        quote["used"] = True
        quote["used_at"] = now.isoformat(timespec="seconds")
        save_json(config.QUOTES, quotes)

        journal.setdefault("posts", {})["%s_%02d" % (day, slot)] = {
            "quote_id": quote["id"],
            "topic": quote["topic"],
            "media_id": media_id,
            "thread_id": thread_id,
            "index": index,
            "slot": slot,
            "kind": "reel",
            "style": meta["style"],
            "cta": cta,
            "effect": meta["effect"],
            "theme": meta["theme"],
            "source": source,
            "duration": duration,
            "youtube_id": youtube_id,
            "ig_kind": ig_kind,
            "ig_theme": ig_theme,
            "at": now.isoformat(timespec="seconds"),
        }
        journal["counter"] = index + 1
        save_json(LOG_PATH, journal)

        drop_local(media_path)
        if ig_path != media_path:
            drop_local(ig_path)

        left = len(unused(quotes))
        log("Опубликовано, media_id %s. Осталось цитат: %d" % (media_id, left))
        if left < 10:
            log("ВНИМАНИЕ: цитаты заканчиваются, пополни quotes/quotes.json")
        return 0

    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
