# -*- coding: utf-8 -*-
"""Единый список фраз канала: порядок выхода и проверка.

Все фразы — старая база, классика и готовые ролики — лежат в quotes/quotes.json
в порядке выхода. Автопост берёт первую невышедшую фразу со статусом «в плане»:
у фразы с готовым роликом публикуется он, для остальных ролик собирает движок.
Что уже вышло, знает только журнал на сервере, поэтому сам список там не
меняется и обновляется через git pull без конфликтов.
"""

import json
import sys

import add_quotes
import config

RUBRICS = ("цитата", "мотивация", "совет")
PLANNED = "в плане"
TIER_PRIORITY = {"A": 2, "B": 3, "C": 4}
TOPIC_COOLDOWN = 8


def load():
    with open(config.QUOTES, encoding="utf-8") as f:
        return json.load(f)


def save(data):
    with open(config.QUOTES, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def planned(data):
    """Фразы в расписании, в порядке выхода."""
    return [q for q in data["quotes"] if q.get("status", PLANNED) == PLANNED]


def priority(quote):
    """Чем меньше, тем раньше: готовый ролик, одобренное владельцем, затем по оценке."""
    if quote.get("video"):
        return 0
    if quote.get("approved"):
        return 1
    return TIER_PRIORITY.get(quote.get("tier"), TIER_PRIORITY["B"])


def rubric_sequence(counts):
    """Рубрика на каждую позицию: каждая идёт равномерно на весь срок и не кончается раньше других."""
    total = sum(counts.values())
    used = dict.fromkeys(counts, 0)
    sequence = []
    for position in range(1, total + 1):
        rubric = max((r for r in counts if used[r] < counts[r]),
                     key=lambda r: (position * counts[r] / total - used[r], -RUBRICS.index(r)))
        used[rubric] += 1
        sequence.append(rubric)
    return sequence


def build_order(items):
    """Порядок выхода: рубрики вперемешку, лучшее раньше, одна тема не чаще раза в два дня."""
    pools = {r: sorted((q for q in items if q["rubric"] == r), key=priority) for r in RUBRICS}
    order = []
    for rubric in rubric_sequence({r: len(p) for r, p in pools.items() if p}):
        pool = pools[rubric]
        recent = {q["topic"] for q in order[-TOPIC_COOLDOWN:]}
        best = priority(pool[0])
        pick = (next((q for q in pool if priority(q) == best and q["topic"] not in recent), None)
                or next((q for q in pool if q["topic"] not in recent), pool[0]))
        pool.remove(pick)
        order.append(pick)
    return order


def reorder():
    """Пересобирает порядок фраз в расписании; вышедшие и отклонённые остаются в конце."""
    data = load()
    items = planned(data)
    ids = {q["id"] for q in items}
    data["quotes"] = build_order(items) + [q for q in data["quotes"] if q["id"] not in ids]
    save(data)
    print("Порядок пересобран: %d фраз в расписании" % len(items))


def attach_videos(videos):
    """Привязывает готовые ролики к фразам списка по тексту; возвращает непривязанные."""
    data = load()
    by_text = {add_quotes.normalize(q["text"]): q for q in planned(data)}
    missing = []
    for video in videos:
        quote = by_text.get(add_quotes.normalize(video["text"]))
        if quote:
            quote["video"] = {k: v for k, v in video.items() if k != "text"}
        else:
            missing.append(video)
    save(data)
    return missing


def check():
    """Проверка каждой фразы в расписании: знаки, длина, рубрика, поля, повторы."""
    seen, flagged = {}, 0
    for q in planned(load()):
        issues = add_quotes.lint(q["text"])
        if q.get("rubric") not in RUBRICS:
            issues.append("рубрика «%s» не из списка" % q.get("rubric"))
        issues += ["нет поля %s" % key for key in ("topic", "query", "question") if not q.get(key)]
        if q.get("question") and not q["question"].endswith("?"):
            issues.append("вопрос без знака вопроса")
        key = add_quotes.normalize(q["text"])
        if key in seen:
            issues.append("повторяет фразу #%s" % seen[key])
        seen.setdefault(key, q["id"])
        if issues:
            flagged += 1
            print("#%s %s — %s" % (q["id"], q["text"], "; ".join(issues)))
    print("Проверено %d фраз, с замечаниями: %d" % (len(seen), flagged))
    return flagged


def summary():
    """Сколько фраз в расписании и как они делятся по рубрикам и оценкам."""
    items = planned(load())
    days = len(items) // len(config.get("SLOTS", "9,13,19,0").split(","))
    print("В расписании %d фраз — на %d дней" % (len(items), days))
    print("По рубрикам: %s" % ", ".join(
        "%s — %d" % (r, sum(1 for q in items if q["rubric"] == r)) for r in RUBRICS))
    print("Готовых роликов: %d, одобрено владельцем: %d, оценки: %s" % (
        sum(1 for q in items if q.get("video")), sum(1 for q in items if q.get("approved")),
        ", ".join("%s — %d" % (t, sum(1 for q in items if q.get("tier") == t)) for t in TIER_PRIORITY)))


def main():
    args = sys.argv[1:]
    if "--order" in args:
        reorder()
    if "--check" in args:
        check()
    if not {"--order", "--check"} & set(args):
        print("Использование: python quotes_list.py [--order] [--check]")
    summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())
