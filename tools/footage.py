# -*- coding: utf-8 -*-
"""Вертикальный видеоряд под ролик из бесплатного стока Pexels.

Клип ищется по очередному запросу из списка, скачивается в кэш и не
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
MAX_SECONDS = 40
CACHE_LIMIT = 24

DEFAULT_QUERIES = [
    "calm nature aerial", "rain on window", "ocean waves slow", "forest fog morning",
    "city lights night", "walking alone street", "mountains clouds timelapse",
    "sunrise field", "river flowing", "snow falling", "lake reflection", "desk work laptop",
]

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


def trim_cache(used):
    """Держит кэш в пределах CACHE_LIMIT клипов: клипы по 20–100 МБ, диск не резиновый."""
    clips = [f for f in os.listdir(CACHE) if f.endswith(".mp4")] if os.path.isdir(CACHE) else []
    clips.sort(key=lambda f: used.get(f[:-4], 0))
    for name in clips[:max(0, len(clips) - CACHE_LIMIT)]:
        try:
            os.remove(os.path.join(CACHE, name))
        except OSError:
            pass


def from_cache(used):
    """Самый давно не показанный клип из кэша, если сток недоступен."""
    clips = [f for f in os.listdir(CACHE) if f.endswith(".mp4")] if os.path.isdir(CACHE) else []
    if not clips:
        return None
    clips.sort(key=lambda f: used.get(f[:-4], 0))
    return os.path.join(CACHE, clips[0])


def pick_clip(number, min_seconds=MIN_SECONDS, log=print):
    """Путь к клипу: свежий из стока по очередному запросу, иначе давний из кэша.

    Запрос берётся по счётчику роликов, а не по теме цитаты: под цитату
    из общей базы точный клип всё равно не подобрать, а по кругу фон
    хотя бы не повторяется.
    """
    os.makedirs(CACHE, exist_ok=True)
    used = load_used()
    key = config.get("PEXELS_API_KEY")

    if key:
        start = number % len(DEFAULT_QUERIES)
        queries = DEFAULT_QUERIES[start:] + DEFAULT_QUERIES[:start]
        for query in queries[:6]:
            try:
                videos = search(query, key)
            except Exception as e:  # noqa: BLE001
                log("Pexels не ответил на «%s»: %s" % (query, e))
                continue
            candidates = [v for v in videos
                          if min_seconds <= v.get("duration", 0) <= MAX_SECONDS
                          and fresh(v["id"], used) and best_file(v)]
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
            trim_cache(used)
            log("Клип %d по запросу «%s», автор %s" % (video["id"], query, video.get("user", {}).get("name", "")))
            return path
        log("Сток не дал свежего клипа, беру из кэша")
    else:
        log("PEXELS_API_KEY не задан, беру клип из кэша")

    path = from_cache(used)
    if path:
        used[os.path.basename(path)[:-4]] = time.time()
        save_used(used)
    return path


def main():
    number = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    path = pick_clip(number)
    print("клип:", path)
    return 0 if path else 1


if __name__ == "__main__":
    sys.exit(main())
