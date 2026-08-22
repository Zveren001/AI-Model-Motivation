# -*- coding: utf-8 -*-
"""Добавление цитат в базу с проверкой на дубли.

Сравнение идёт по нормализованному тексту: без регистра, пунктуации и ё/е,
поэтому «Не жди момента» и «не жди момента!» считаются одним и тем же.
"""

import json
import os
import re
import sys

import config


def normalize(text):
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


SUSPICIOUS = [
    (r"значит(?!,)(?=[^,]*$)", "«значит» как вводное слово требует запятых"),
    (r"^[А-ЯЁ][а-яё]+ (это|не) ", None),
    (r"\s(и|а|но|или)\s*$", "обрывается на союзе"),
    (r"[a-zA-Z]", "латиница в русском тексте"),
    (r"\s{2,}", "двойные пробелы"),
    (r"[.!?]$", "точка или знак в конце — в этом проекте не ставятся"),
    (r"чья-то(?=\s+(ожидание|решение|дело))", "рассогласование рода"),
]


def lint(text):
    """Ищет типовые огрехи: рассогласование, обрывы, лишние знаки."""
    problems = []
    for pattern, message in SUSPICIOUS:
        if message and re.search(pattern, text):
            problems.append(message)

    words = text.split()
    if len(words) < 2:
        problems.append("слишком короткая фраза")

    # Фраза из двух частей, где во второй нет ни глагола, ни союза, часто
    # звучит обрывочно — так в базу попало «Сомневаться нормально, идти всё равно».
    # Придаточные с союзом при этом нормальны: «больше, чем просили».
    if "," in text:
        tail = text.split(",")[-1].strip()
        starts_clause = tail.split()[0].lower() in (
            "чем", "если", "когда", "что", "зачем", "как", "пока", "чтобы",
            "кто", "где", "куда", "а", "но", "и", "или", "это", "значит",
            "который", "которая", "которое", "которые", "чтоб", "раз", "хоть",
        ) if tail else False
        verb_endings = ("ть", "шь", "ет", "ёт", "ут", "ют", "ит", "ат", "ят",
                        "но", "ся", "ай", "ей", "уй", "ло", "ла", "ли", "ем",
                        "им", "ешь", "ишь", "тся")
        # глагол может стоять любым словом в хвосте, а не только последним
        has_verb = any(w.lower().endswith(verb_endings) for w in tail.split())
        if tail and len(tail.split()) <= 2 and not starts_clause and not has_verb:
            problems.append("вторая часть выглядит обрывочной: «%s»" % tail)

    return problems


def load():
    if not os.path.exists(config.QUOTES):
        return {"quotes": []}
    with open(config.QUOTES, encoding="utf-8") as f:
        return json.load(f)


def save(data):
    with open(config.QUOTES, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add(pairs, verbose=True):
    """pairs — список (текст, тема). Возвращает сколько добавлено и сколько отсеяно."""
    data = load()
    seen = {normalize(q["text"]) for q in data["quotes"]}
    next_id = max((q["id"] for q in data["quotes"]), default=0) + 1

    added, skipped = 0, []
    for text, topic in pairs:
        text = text.strip().rstrip(".")
        key = normalize(text)
        if not key or key in seen:
            skipped.append(text)
            continue
        issues = lint(text)
        if issues and verbose:
            print("  проверь: %s" % text)
            for i in issues:
                print("     %s" % i)

        seen.add(key)
        data["quotes"].append({
            "id": next_id, "text": text, "topic": topic,
            "used": False, "used_at": None,
        })
        next_id += 1
        added += 1

    save(data)

    if verbose:
        print("добавлено: %d, отсеяно дублей: %d" % (added, len(skipped)))
        for s in skipped[:5]:
            print("   дубль:", s)
        print("всего в базе:", len(data["quotes"]))
    return added, len(skipped)


def lint_all():
    """Прогоняет всю базу через проверку — для контроля после правок."""
    data = load()
    flagged = 0
    for q in data["quotes"]:
        issues = lint(q["text"])
        if issues:
            flagged += 1
            print("%4d %s" % (q["id"], q["text"]))
            for i in issues:
                print("       %s" % i)
    print()
    print("помечено к проверке: %d из %d" % (flagged, len(data["quotes"])))


def stats():
    data = load()
    quotes = data["quotes"]
    used = sum(1 for q in quotes if q.get("used"))
    topics = {}
    for q in quotes:
        topics[q["topic"]] = topics.get(q["topic"], 0) + 1

    print("всего цитат: %d" % len(quotes))
    print("использовано: %d, осталось: %d" % (used, len(quotes) - used))
    print("тем: %d" % len(topics))
    print("хватит на %d дней при 2 постах, на %d при 4"
          % ((len(quotes) - used) // 2, (len(quotes) - used) // 4))

    lens = [len(q["text"]) for q in quotes]
    print("длина: от %d до %d символов, в среднем %d"
          % (min(lens), max(lens), sum(lens) // len(lens)))

    longest = sorted(quotes, key=lambda q: -len(q["text"]))[:3]
    print("самые длинные:")
    for q in longest:
        print("   %d симв: %s" % (len(q["text"]), q["text"]))


if __name__ == "__main__":
    if "--stats" in sys.argv:
        stats()
    elif "--lint" in sys.argv:
        lint_all()
    else:
        print("Модуль для добавления цитат. Запуск с --stats покажет статистику базы.")
