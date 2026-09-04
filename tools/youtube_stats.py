# -*- coding: utf-8 -*-
"""Сбор статистики роликов YouTube в stats.json и их оценка для выбора тем.

Раз в сутки по cron: просмотры, лайки и комментарии из Data API, вовлечённые
просмотры, досмотр и подписки из Analytics API. По этим числам autopost.py
решает, каким темам, форматам и призывам давать больше слотов.

Метрику «выбрали просмотр» из Студии API не отдаёт, её заменяет доля
вовлечённых просмотров (engagedViews) от всех. Аналитика отстаёт на два-три
дня, поэтому вовлечённые просмотры у свежих роликов появляются позже обычных.

Нужны права youtube.force-ssl и yt-analytics.readonly: без них скрипт
пишет в лог, что прав нет, и выходит, публикацию это не трогает.
"""

import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import config
import youtube_publish

STATS = os.path.join(config.ROOT, "stats.json")
LOG = os.path.join(config.ROOT, "post_log.json")

VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
ANALYTICS_METRICS = ("views,engagedViews,likes,comments,shares,"
                     "averageViewPercentage,subscribersGained")
CHUNK = 50

# Оценка ролика — просмотры на первом замере старше суток: к этому моменту
# тестовая порция показов уже роздана, а старые ролики не выигрывают
# просто за счёт возраста
MIN_AGE = datetime.timedelta(hours=24)
TZ = datetime.timezone(datetime.timedelta(hours=3))


def parse_time(value):
    stamp = datetime.datetime.fromisoformat(value)
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=TZ)


def load():
    if not os.path.exists(STATS):
        return {"updated": None, "videos": {}}
    try:
        with open(STATS, encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return {"updated": None, "videos": {}}


def save(stats):
    with open(STATS, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


def video_score(stats, video_id):
    """Просмотры на первом замере старше суток; для молодых и неизвестных — None."""
    video = stats.get("videos", {}).get(video_id) if video_id else None
    if not video or not video.get("published"):
        return None
    published = parse_time(video["published"])
    for day in sorted(video.get("history", {})):
        snapshot = video["history"][day]
        if parse_time(snapshot["at"]) - published >= MIN_AGE:
            return snapshot.get("views", 0)
    return None


def engaged_share(video):
    views, engaged = video.get("views") or 0, video.get("engaged_views")
    if not views or engaged is None:
        return None
    return engaged / float(views)


def get_json(url, params, token):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params))
    req.add_header("Authorization", "Bearer %s" % token)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def chunks(items):
    for i in range(0, len(items), CHUNK):
        yield items[i:i + CHUNK]


def fetch_statistics(token, ids):
    """Просмотры, лайки и комментарии из Data API: часть statistics, по 50 роликов за раз."""
    out = {}
    for part in chunks(ids):
        data = get_json(VIDEOS_URL, {"part": "statistics", "id": ",".join(part)}, token)
        for item in data.get("items", []):
            s = item.get("statistics", {})
            out[item["id"]] = {
                "views": int(s.get("viewCount", 0)),
                "likes": int(s.get("likeCount", 0)),
                "comments": int(s.get("commentCount", 0)),
            }
    return out


def fetch_analytics(token, ids, since):
    """Вовлечённые просмотры, досмотр и подписки из Analytics API по каждому ролику."""
    out = {}
    today = datetime.date.today().isoformat()
    for part in chunks(ids):
        data = get_json(ANALYTICS_URL, {
            "ids": "channel==MINE",
            "startDate": since,
            "endDate": today,
            "metrics": ANALYTICS_METRICS,
            "dimensions": "video",
            "filters": "video==" + ",".join(part),
            "maxResults": CHUNK,
        }, token)
        names = [h["name"] for h in data.get("columnHeaders", [])]
        for row in data.get("rows", []):
            values = dict(zip(names, row))
            out[values["video"]] = {
                "engaged_views": int(values.get("engagedViews", 0)),
                "shares": int(values.get("shares", 0)),
                "view_pct": round(float(values.get("averageViewPercentage", 0)), 1),
                "subscribers": int(values.get("subscribersGained", 0)),
            }
    return out


def explain(error):
    body = error.read().decode(errors="replace")[:600] if hasattr(error, "read") else str(error)
    if "insufficient" in body.lower() or "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in body:
        return "нет прав у токена, нужен перевыпуск по docs/youtube-token.md"
    if "accessNotConfigured" in body or "has not been used" in body:
        return "API не включён в проекте Google Cloud, см. docs/youtube-token.md"
    return body


def journal_videos():
    """Ролики из журнала публикаций: id на YouTube, цитата и время выхода."""
    if not os.path.exists(LOG):
        return {}
    with open(LOG, encoding="utf-8") as f:
        posts = json.load(f).get("posts", {})
    return {p["youtube_id"]: p for p in posts.values() if p.get("youtube_id")}


def collect():
    stats = load()
    posts = journal_videos()
    if not posts:
        print("В журнале нет роликов с YouTube")
        return stats

    token = youtube_publish.access_token()
    ids = sorted(posts)
    now = datetime.datetime.now(TZ).isoformat(timespec="seconds")
    today = datetime.date.today().isoformat()

    try:
        basic = fetch_statistics(token, ids)
    except urllib.error.HTTPError as e:
        print("Data API: %s" % explain(e))
        return None

    since = min(parse_time(p["at"]) for p in posts.values()).date().isoformat()
    try:
        deep = fetch_analytics(token, ids, since)
    except urllib.error.HTTPError as e:
        print("Analytics API: %s" % explain(e))
        deep = {}

    for video_id in ids:
        post = posts[video_id]
        entry = stats["videos"].setdefault(video_id, {
            "quote_id": post.get("quote_id"),
            "published": post.get("at"),
            "history": {},
        })
        entry.update(basic.get(video_id, {}))
        entry.update(deep.get(video_id, {}))
        entry["history"][today] = {
            "at": now,
            "views": entry.get("views", 0),
            "engaged_views": entry.get("engaged_views"),
        }

    stats["updated"] = now
    save(stats)
    return stats


def summary(stats):
    posts = journal_videos()
    print("Обновлено: %s, роликов: %d" % (stats.get("updated"), len(stats.get("videos", {}))))
    print("%-12s %7s %6s %6s %6s %6s  %-6s %-14s %s"
          % ("дата", "просм", "вовл%", "лайки", "комм", "оценка", "формат", "тема", "цитата"))
    groups = {"format": {}, "cta": {}, "topic": {}}
    for video_id, video in sorted(stats.get("videos", {}).items(),
                                  key=lambda kv: kv[1].get("published", "")):
        post = posts.get(video_id, {})
        share = engaged_share(video)
        score = video_score(stats, video_id)
        print("%-12s %7d %6s %6d %6d %6s  %-6s %-14s #%s"
              % (video.get("published", "")[:10], video.get("views", 0),
                 "%.0f" % (share * 100) if share is not None else "-",
                 video.get("likes", 0), video.get("comments", 0),
                 score if score is not None else "-",
                 post.get("format") or "short", post.get("topic") or "",
                 video.get("quote_id")))
        if score is None:
            continue
        for field in groups:
            if field in post:
                groups[field].setdefault(post[field], []).append(score)

    for field, label in (("format", "Формат"), ("cta", "Призыв"), ("topic", "Тема")):
        if not groups[field]:
            continue
        print()
        print("%s — средняя оценка:" % label)
        for value, scores in sorted(groups[field].items(),
                                    key=lambda kv: -sum(kv[1]) / len(kv[1])):
            print("   %-16s %7.0f  (роликов: %d)"
                  % (value, sum(scores) / len(scores), len(scores)))


def check():
    """Права токена и текущая сводка — для проверки после перевыпуска токена."""
    token = youtube_publish.access_token()
    with urllib.request.urlopen(TOKENINFO_URL + "?access_token=" + token, timeout=60) as resp:
        info = json.loads(resp.read())
    scopes = info.get("scope", "").split()
    print("Права токена:")
    for scope in scopes:
        print("   " + scope)
    need = ["youtube.force-ssl", "yt-analytics.readonly"]
    missing = [n for n in need if not any(s.endswith(n) for s in scopes)]
    if missing:
        print("Не хватает: %s — см. docs/youtube-token.md" % ", ".join(missing))
    else:
        print("Прав достаточно для статистики")
    print()
    summary(load())


def main():
    if not youtube_publish.configured():
        print("YT_REFRESH_TOKEN не задан, статистику собирать нечем")
        return 1
    if "--check" in sys.argv:
        check()
        return 0
    if "--summary" in sys.argv:
        summary(load())
        return 0

    stats = collect()
    if stats is None:
        return 1
    summary(stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
