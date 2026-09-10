# -*- coding: utf-8 -*-
"""Автопубликация по расписанию: один запуск — один ролик на YouTube и в Instagram.

Фразы выходят строго по единому списку quotes/quotes.json — порядок, рубрики
и темы в нём уже расставлены (quotes_list.py). В слот идёт первая невышедшая
фраза: если к ней есть готовый ролик из queue/, публикуется он, иначе ролик
собирает движок compose. Кончился список — слот пропускается.
Эффект, обработка фона, подача текста и голос идут по кругу
только среди одобренных вариантов; голос звучит в двух слотах из четырёх,
и какие это слоты, меняется по дням, чтобы голос не срастался со временем.

Под роликом на YouTube первым комментарием от канала выходит вопрос
с выбором из двух вариантов; в Instagram — тоже, если у токена есть право
на комментарии, иначе это только отмечается в логе.

Час публикации задаёт cron, минуты внутри часа добирает случайная пауза,
поэтому ключ --now нужен ручному запуску, чтобы не ждать её.

Защита от повторов трёхуровневая, потому что cron может сработать
дважды при перезапуске сервера или сдвиге времени:
1. Журнал post_log.json — какой слот какого дня отработан и какие ролики
   и фразы уже вышли.
2. Сверка номера и текста фразы с журналом — одна мысль не выходит дважды.
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

import add_quotes
import compose
import config
import footage
import github_upload
import meta_net
import quotes_list
import typefx
import youtube_publish

API = "https://graph.instagram.com/v21.0"

LOG_PATH = os.path.join(config.ROOT, "post_log.json")
LOCK_PATH = os.path.join(config.ROOT, ".autopost.lock")
RUN_LOG = os.path.join(config.ROOT, "autopost.log")
QUEUE_DIR = os.path.join(config.ROOT, "queue")

# Блокировка переживает разброс времени вместе со сборкой ролика: полчаса сна,
# озвучка, скачивание клипа и кодирование легко перекрывают прежние пятнадцать минут.
LOCK_TTL = 3600
NET_ATTEMPTS = 8
NET_DELAY = 20

JITTER_MIN = 15 * 60
JITTER_MAX = 30 * 60

RUBRIC_TAGS = {"цитата": "#цитаты", "мотивация": "#мотивация", "совет": "#советы"}
CAPTION_TAGS = ["#мотивация", "#мысли", "#саморазвитие"]

# Вертикальное видео короче трёх минут YouTube сам относит к Shorts,
# хэштег в описании только помогает ему определиться быстрее
YOUTUBE_TAGS = ["#shorts", "#мотивация"]
YOUTUBE_KEYWORDS = ["мотивация", "саморазвитие", "мысли", "shorts"]
FOOTAGE_CREDIT = "Видеоряд: pexels.com"
LOW_STOCK_DAYS = 14

# Только варианты, одобренные на утверждении образцов 10.09.2026
EFFECTS = typefx.ORDER
GRADES = ("dark", "blur", "bw", "warm", "zoom")
VOICES = ("обычный", "медленный", "бодрый", "с акцентом", "низкий")

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
    """Собранный ролик уже в хранилище — локальная копия не нужна ни после успеха, ни после сбоя.

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


def already_posted(journal, day, slot):
    key = "%s_%02d" % (day.isoformat(), slot)
    return key in journal.get("posts", {})


def reels(journal):
    return [p for p in journal.get("posts", {}).values() if p.get("kind") == "reel"]


def published_texts(journal):
    return {add_quotes.normalize(p["text"]) for p in reels(journal) if p.get("text")}


def remaining(journal):
    """Фразы списка, которые ещё не выходили роликом, в порядке выхода."""
    posts = reels(journal)
    ids = {p.get("quote_id") for p in posts} - {None}
    texts = published_texts(journal)
    return [q for q in quotes_list.planned(quotes_list.load())
            if q["id"] not in ids and add_quotes.normalize(q["text"]) not in texts]


def log_stock(journal):
    """Сколько фраз осталось в списке и на сколько дней их хватит."""
    left = remaining(journal)
    days = len(left) // len(slots())
    log("В списке осталось %d фраз, на %d дней: %s" % (len(left), days, ", ".join(
        "%s — %d" % (r, sum(1 for q in left if q["rubric"] == r)) for r in quotes_list.RUBRICS)))
    if days < LOW_STOCK_DAYS:
        log("ВНИМАНИЕ: фраз осталось меньше чем на %d дней" % LOW_STOCK_DAYS)


def voiced_slot(now, slot):
    """Голос в двух слотах из четырёх; по чётным дням — в первом и третьем, по нечётным — во втором и четвёртом."""
    order = slots()
    index = order.index(slot) if slot in order else 0
    return (now.date().toordinal() + index) % 2 == 0


def engine_variant(journal, now, slot):
    """Эффект, фон, подача текста и голос для ролика, собираемого движком.

    Эффектов девять, фонов пять — числа взаимно простые, поэтому по кругу
    за 45 роликов выпадают все их сочетания.
    """
    built = [p for p in reels(journal) if p.get("source") == "engine"]
    n = len(built)
    voice = "нет"
    if voiced_slot(now, slot):
        voice = VOICES[sum(1 for p in built if p.get("voice") not in (None, "нет")) % len(VOICES)]
    return {"effect": EFFECTS[n % len(EFFECTS)], "grade": GRADES[n % len(GRADES)],
            "text_style": "крупно" if n % 3 == 2 else "тень", "voice": voice}


def unique(items):
    return list(dict.fromkeys(items))


def caption_for(text, rubric):
    return "%s\n\n%s" % (text, " ".join(unique([RUBRIC_TAGS[rubric]] + CAPTION_TAGS)))


def topic_tag(topic):
    return "#" + re.sub(r"[^\w]", "", topic)


def youtube_meta(text, topic, rubric):
    """Заголовок, описание и ключевые слова ролика для YouTube."""
    tags = unique(YOUTUBE_TAGS[:1] + [RUBRIC_TAGS[rubric]] + YOUTUBE_TAGS[1:] + [topic_tag(topic)])
    description = "\n\n".join([text, FOOTAGE_CREDIT, " ".join(tags)])
    return text[:100], description, unique(YOUTUBE_KEYWORDS + [RUBRIC_TAGS[rubric][1:], topic])


def publish_reel(url, caption, attempts=48):
    """Публикует ролик в Instagram по готовой ссылке и возвращает media_id.

    Видео обрабатывается дольше картинки, поэтому статус опрашивается терпеливо.
    """
    user_id = config.get("IG_USER_ID", required=True)
    token = config.get("IG_ACCESS_TOKEN", required=True)
    container = meta_net.post("%s/%s/media" % (API, user_id), {
        "media_type": "REELS", "video_url": url, "share_to_feed": "true",
        "caption": caption, "access_token": token})
    creation_id = container["id"]

    for _ in range(attempts):
        time.sleep(5)
        status = meta_net.get("%s/%s" % (API, creation_id),
                              {"fields": "status_code", "access_token": token})
        code = status.get("status_code")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError("Instagram не смог обработать ролик")
    else:
        raise RuntimeError("Контейнер не обработался за отведённое время")

    result = meta_net.post("%s/%s/media_publish" % (API, user_id), {
        "creation_id": creation_id, "access_token": token})
    return result.get("id")


def instagram_comment(media_id, text):
    """Первый комментарий в Instagram; нужно право instagram_business_manage_comments."""
    result = meta_net.post("%s/%s/comments" % (API, media_id), {
        "message": text, "access_token": config.get("IG_ACCESS_TOKEN", required=True)})
    return result.get("id")


def sleep_jitter():
    """Разброс перед публикацией, чтобы посты не выходили секунда в секунду.

    Час задаёт cron, минуты внутри часа — эта пауза: ровное расписание
    читается как автопостинг и самой площадкой, и живым читателем.
    """
    delay = random.randint(JITTER_MIN, JITTER_MAX)
    log("Разброс: пауза %d мин %d сек" % (delay // 60, delay % 60))
    time.sleep(delay)


def error_text(e):
    return e.read().decode("utf-8", "replace")[:400] if hasattr(e, "read") else str(e)


def prepare(journal, now, slot, day, force, engine_only):
    """Ролик для слота: готовый или собранный движком по следующей фразе списка. None — публиковать нечего."""
    left = remaining(journal)
    if not left:
        log("Фразы в списке закончились — слот пропущен")
        return None
    quote = left[0]
    phrase = {"quote_id": quote["id"], "text": quote["text"], "topic": quote["topic"],
              "question": quote["question"], "rubric": quote["rubric"]}
    video = quote.get("video")
    if video and not engine_only:
        path = os.path.join(QUEUE_DIR, video["file"])
        if os.path.exists(path):
            log("Готовый ролик, фраза #%d, рубрика «%s», образец №%02d: %s"
                % (quote["id"], quote["rubric"], video["sample"], quote["text"]))
            return dict(video, **phrase, path=path, source="queue", clip=video["clip_id"])
        log("Нет файла готового ролика %s — собираю движком" % video["file"])

    variant = engine_variant(journal, now, slot)
    variant.update({k: v for k, v in force.items() if v})
    log("Сборка по фразе #%d, рубрика «%s», «%s»: эффект %s, фон %s, текст %s, голос %s"
        % (quote["id"], quote["rubric"], quote["text"], variant["effect"], variant["grade"],
           variant["text_style"], variant["voice"]))
    clip = footage.pick_for_query(quote["query"], log=log)
    if not clip:
        log("Нет видеоряда: сток недоступен и кэш пуст — слот пропущен")
        return None
    path = os.path.join(config.OUTPUT, "%s_%02d.mp4" % (day, slot))
    duration = compose.render(quote["text"], path, clip, variant["effect"], variant["grade"],
                              variant["text_style"], variant["voice"], seed=quote["id"])
    log("Ролик собран: %.1f с" % duration)
    return dict(variant, **phrase, path=path, source="engine", sample=None,
                clip=os.path.basename(clip)[:-4], duration=duration)


def main():
    dry = "--dry-run" in sys.argv
    engine_only = "--engine" in sys.argv
    force_slot = None
    force = {"effect": None, "grade": None, "text_style": None, "voice": None}
    for a in sys.argv:
        if a.startswith("--slot="):
            force_slot = int(a.split("=", 1)[1])
        for key in force:
            if a.startswith("--%s=" % key.replace("_", "-")):
                force[key] = a.split("=", 1)[1]

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
        day = now.date().isoformat()
        if already_posted(journal, now.date(), slot):
            log("Слот %02d:00 сегодня уже отработан, выхожу" % slot)
            return 0

        index = journal.get("counter", 0)
        log("Слот %02d:00, пост #%d" % (slot, index + 1))
        post = prepare(journal, now, slot, day, force, engine_only)
        if not post:
            return 1

        if dry:
            log_stock(journal)
            log("Проверка завершена, ничего не отправлено")
            if post["source"] == "engine":
                drop_local(post["path"])
            return 0

        if "--now" not in sys.argv:
            sleep_jitter()

        if not wait_for_network():
            log("Сеть недоступна, публикация отложена")
            if post["source"] == "engine":
                drop_local(post["path"])
            return 1

        name = "%s_%02d.mp4" % (day, slot)
        media_url = github_upload.upload(post["path"], "motivation/%s" % name)
        log("Загружено: %s" % media_url)

        try:
            media_id = publish_reel(media_url, caption_for(post["text"], post["rubric"]))
        except (urllib.error.HTTPError, RuntimeError, KeyError) as e:
            log("ОШИБКА публикации в Instagram: %s" % error_text(e))
            if post["source"] == "engine":
                drop_local(post["path"])
            return 1
        log("Instagram: опубликовано, media_id %s" % media_id)

        ig_comment = None
        try:
            ig_comment = instagram_comment(media_id, post["question"])
            log("Instagram: первый комментарий %s" % ig_comment)
        except (urllib.error.HTTPError, RuntimeError, KeyError, ValueError) as e:
            log("Instagram не принял комментарий: %s" % error_text(e))

        youtube_id, yt_comment = None, None
        if youtube_publish.configured():
            title, description, keywords = youtube_meta(post["text"], post["topic"], post["rubric"])
            try:
                youtube_id, privacy = youtube_publish.publish(
                    post["path"], title, description, tags=keywords)
                log("YouTube: опубликовано, id %s, доступ %s" % (youtube_id, privacy))
                yt_comment = youtube_publish.comment(youtube_id, post["question"])
                log("YouTube: первый комментарий %s" % yt_comment)
            except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError,
                    ValueError, KeyError) as e:
                log("YouTube: сбой — %s" % error_text(e))

        journal.setdefault("posts", {})["%s_%02d" % (day, slot)] = {
            "kind": "reel", "source": post["source"], "sample": post.get("sample"),
            "quote_id": post.get("quote_id"), "rubric": post["rubric"],
            "text": post["text"], "topic": post["topic"],
            "question": post["question"], "effect": post["effect"], "grade": post["grade"],
            "text_style": post["text_style"], "voice": post["voice"], "clip": post["clip"],
            "duration": post["duration"], "media_id": media_id, "ig_comment": ig_comment,
            "youtube_id": youtube_id, "yt_comment": yt_comment, "index": index,
            "slot": slot, "at": now.isoformat(timespec="seconds"),
        }
        journal["counter"] = index + 1
        save_json(LOG_PATH, journal)

        if post["source"] == "engine":
            drop_local(post["path"])

        log("Опубликовано")
        log_stock(journal)
        return 0

    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
