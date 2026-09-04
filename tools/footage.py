# -*- coding: utf-8 -*-
"""Вертикальный видеоряд под ролик из бесплатного стока Pexels.

Клип ищется по ключевым словам темы цитаты, скачивается в кэш и не
повторяется раньше чем через месяц. Ключ PEXELS_API_KEY в .env, лимит
200 запросов в час — при двух роликах в сутки это ничто.

Если стока нет — ключ пуст или сеть не отвечает — берётся любой клип
из кэша, который давно не показывался. Совсем без клипов ролик не
собирается: пустой фон хуже пропущенного слота.
"""

import json
import os
import random
import sys
import time
import urllib.parse
import urllib.request

import config

SEARCH_URL = "https://api.pexels.com/videos/search"
CACHE = os.path.join(config.ROOT, "footage")
USED = os.path.join(CACHE, "used.json")
REUSE_AFTER = 30 * 24 * 3600
PER_PAGE = 40
MIN_SECONDS = 8

DEFAULT_QUERIES = [
    "calm nature aerial", "rain on window", "ocean waves slow", "forest fog morning",
    "city lights night", "walking alone street", "mountains clouds timelapse",
    "sunrise field", "river flowing", "snow falling", "lake reflection", "desk work laptop",
]

TOPIC_QUERIES = {
    "тревога": ["rain on window", "storm clouds", "night city rain"],
    "спокойствие": ["calm lake", "ocean waves slow", "fog forest"],
    "тишина": ["snow falling", "calm lake", "candle"],
    "фокус": ["desk work laptop", "writing notebook", "coffee desk"],
    "действие": ["running road morning", "walking street", "climbing mountain"],
    "начало": ["sunrise field", "road morning", "open door light"],
    "путь": ["road aerial", "walking trail", "train window"],
    "время": ["clock", "timelapse city", "sand"],
    "работа": ["desk work laptop", "workshop hands", "typing keyboard"],
    "труд": ["workshop hands", "typing keyboard", "construction sunset"],
    "дисциплина": ["running track", "gym training", "early morning street"],
    "привычки": ["morning routine coffee", "running road morning", "notebook writing"],
    "прокрастинация": ["clock", "empty desk", "rain window"],
    "лень": ["morning bed light", "clock", "rain window"],
    "здоровье": ["running park", "water drink", "forest walk"],
    "спорт": ["running track", "gym training", "swimming"],
    "отдых": ["hammock", "beach sunset", "reading book"],
    "забота": ["tea cup window", "blanket cozy", "walking park"],
    "страх": ["dark forest fog", "cliff edge", "night road"],
    "риск": ["cliff edge", "surfing wave", "highway night"],
    "смелость": ["mountain summit", "surfing wave", "jump water"],
    "ошибки": ["broken glass", "rain street", "notebook crumpled"],
    "рост": ["plant growing timelapse", "sunrise mountains", "tree forest"],
    "обучение": ["library books", "writing notebook", "reading"],
    "мастерство": ["craftsman hands", "pottery", "workshop"],
    "цель": ["mountain summit", "archery", "road horizon"],
    "мечта": ["stars night sky", "sky clouds", "sea horizon"],
    "деньги": ["city skyline", "coins", "office window"],
    "отношения": ["couple walking", "holding hands", "friends laughing"],
    "семья": ["family walk", "home kitchen", "children park"],
    "границы": ["fence field", "door closing", "window rain"],
    "окружение": ["friends talking", "crowd street", "cafe people"],
    "поддержка": ["holding hands", "friends hug", "tea together"],
    "одиночество": ["alone bench", "empty beach", "window night"],
    "сравнение": ["crowd walking", "mirror", "city people"],
    "принятие": ["calm lake", "sunset beach", "hands open"],
    "честность": ["mirror", "candle", "window light"],
    "выбор": ["crossroads", "fork road", "doors"],
    "перемены": ["seasons timelapse", "leaves falling", "sunrise"],
    "счастье": ["sunlight field", "laughing", "beach sunset"],
    "мысли": ["clouds timelapse", "window rain", "night sky"],
    "мышление": ["chess", "notebook", "clouds"],
    "терпение": ["plant growing timelapse", "sand hourglass", "river slow"],
    "упорство": ["climbing", "running rain", "waves rocks"],
    "утро": ["sunrise", "morning coffee", "morning light window"],
    "возраст": ["old hands", "autumn leaves", "tree"],
    "жизнь": ["city timelapse", "sea horizon", "field wind"],
    "смысл": ["stars night", "candle", "sea horizon"],
    "надежда": ["sunrise", "light through clouds", "rainbow"],
    "вера": ["light through clouds", "candle", "sunrise"],
    "творчество": ["painting", "guitar", "notebook sketch"],
    "простота": ["minimal room", "tea", "field"],
    "характер": ["mountain", "rock waves", "storm"],
    "ответственность": ["hands work", "keys", "desk"],
    "уважение": ["handshake", "tea together", "walking together"],
    "доброта": ["helping hand", "smile", "flowers"],
    "внимание": ["eye close", "candle", "coffee steam"],
    "настоящее": ["sunlight leaves", "coffee steam", "walking"],
    "итоги": ["sunset", "notebook", "road"],
    "зрелость": ["autumn", "old tree", "calm sea"],
    "самопознание": ["mirror", "walking alone", "lake reflection"],
}


def queries_for(topic):
    return TOPIC_QUERIES.get(topic, []) + DEFAULT_QUERIES


def load_used():
    if not os.path.exists(USED):
        return {}
    try:
        with open(USED, encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return {}


def save_used(used):
    os.makedirs(CACHE, exist_ok=True)
    with open(USED, "w", encoding="utf-8") as f:
        json.dump(used, f, ensure_ascii=False, indent=2)


def fresh(clip_id, used):
    return time.time() - used.get(str(clip_id), 0) > REUSE_AFTER


def search(query, key):
    params = {"query": query, "orientation": "portrait", "size": "medium", "per_page": PER_PAGE}
    # Без заголовка браузера API отвечает 403: стандартный urllib он отсекает
    req = urllib.request.Request(SEARCH_URL + "?" + urllib.parse.urlencode(params),
                                 headers={"Authorization": key, "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read()).get("videos", [])


def best_file(video):
    """Файл с вертикальной картинкой не меньше 1080 по ширине, самый лёгкий из подходящих."""
    files = [f for f in video.get("video_files", [])
             if f.get("width") and f.get("height") and f["height"] > f["width"]
             and f["width"] >= 1080 and (f.get("file_type") or "").endswith("mp4")]
    if not files:
        return None
    return min(files, key=lambda f: f["width"])


def download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=300) as resp, open(path, "wb") as f:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)


def from_cache(used):
    """Самый давно не показанный клип из кэша, если сток недоступен."""
    clips = [f for f in os.listdir(CACHE) if f.endswith(".mp4")] if os.path.isdir(CACHE) else []
    if not clips:
        return None
    clips.sort(key=lambda f: used.get(f[:-4], 0))
    return os.path.join(CACHE, clips[0])


def pick(topic, min_seconds=MIN_SECONDS, log=print):
    """Путь к клипу под тему: свежий из стока, иначе давний из кэша."""
    os.makedirs(CACHE, exist_ok=True)
    used = load_used()
    key = config.get("PEXELS_API_KEY")

    if key:
        queries = queries_for(topic)
        own = queries[:3]
        random.shuffle(own)
        for query in own + queries[3:6]:
            try:
                videos = search(query, key)
            except Exception as e:  # noqa: BLE001
                log("Pexels не ответил на «%s»: %s" % (query, e))
                continue
            candidates = [v for v in videos
                          if v.get("duration", 0) >= min_seconds and fresh(v["id"], used)
                          and best_file(v)]
            if not candidates:
                continue
            video = random.choice(candidates[:15])
            path = os.path.join(CACHE, "%d.mp4" % video["id"])
            if not os.path.exists(path):
                try:
                    download(best_file(video)["link"], path)
                except Exception as e:  # noqa: BLE001
                    log("Не скачался клип %d: %s" % (video["id"], e))
                    continue
            used[str(video["id"])] = time.time()
            save_used(used)
            log("Клип %d по запросу «%s», автор %s" % (video["id"], query, video.get("user", {}).get("name", "")))
            return path
        log("Сток не дал свежего клипа под тему «%s», беру из кэша" % topic)
    else:
        log("PEXELS_API_KEY не задан, беру клип из кэша")

    path = from_cache(used)
    if path:
        used[os.path.basename(path)[:-4]] = time.time()
        save_used(used)
    return path


def main():
    topic = sys.argv[1] if len(sys.argv) > 1 else "спокойствие"
    path = pick(topic)
    print("клип:", path)
    return 0 if path else 1


if __name__ == "__main__":
    sys.exit(main())
