# -*- coding: utf-8 -*-
"""Утверждение цитат таблицей: в ролики попадает только то, что одобрил человек.

Кандидаты лежат в quotes/candidates.json партиями. Партия выгружается
в папку утверждения таблицей для Excel; после отметок «да/нет» таблица
загружается обратно, и одобренные цитаты переходят в quotes/approved.json —
только оттуда автопост берёт цитаты для новых роликов.
"""

import csv
import json
import os
import sys

import add_quotes
import config

CANDIDATES = os.path.join(config.ROOT, "quotes", "candidates.json")
APPROVED = os.path.join(config.ROOT, "quotes", "approved.json")
OUT = config.get("SAMPLES_DIR", r"C:\Users\Zveren001\Desktop\MotivationReference")
COLUMNS = ["№", "Цитата", "Тема", "Видеоряд", "Вопрос первым комментарием",
           "Утверждаю (да/нет)", "Комментарий"]


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"quotes": []}


def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def table_path(batch):
    return os.path.join(OUT, "Цитаты — партия %d.csv" % batch)


def export(batch):
    """Выгружает партию кандидатов таблицей для отметок."""
    rows = [q for q in load(CANDIDATES)["quotes"] if q["batch"] == batch]
    with open(table_path(batch), "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(COLUMNS)
        for q in rows:
            writer.writerow([q["id"], q["text"], q["topic"], q["scene"], q["question"], "", ""])
    print("Выгружено %d цитат: %s" % (len(rows), table_path(batch)))


def import_marks(batch):
    """Забирает отметки из таблицы: «да» — в утверждённые, комментарии — на экран."""
    candidates = {q["id"]: q for q in load(CANDIDATES)["quotes"]}
    approved = load(APPROVED)
    known = {add_quotes.normalize(q["text"]) for q in approved["quotes"]}
    added, rejected = 0, 0
    with open(table_path(batch), encoding="utf-8-sig") as f:
        for row in csv.DictReader(f, delimiter=";"):
            number = row.get("№", "").strip()
            if not number.isdigit() or int(number) not in candidates:
                continue
            quote = dict(candidates[int(number)])
            verdict = row.get("Утверждаю (да/нет)", "").strip().lower()
            comment = row.get("Комментарий", "").strip()
            if comment:
                print("%s [%s] %s — %s" % (number, verdict or "без отметки", quote["text"], comment))
            if not verdict.startswith("да"):
                rejected += 1
                continue
            quote["text"] = row.get("Цитата", quote["text"]).strip() or quote["text"]
            quote["question"] = row.get("Вопрос первым комментарием", "").strip() or quote["question"]
            if add_quotes.normalize(quote["text"]) in known:
                continue
            approved["quotes"].append(quote)
            known.add(add_quotes.normalize(quote["text"]))
            added += 1
    save(APPROVED, approved)
    print("Утверждено: %d, отклонено: %d, всего в работе: %d"
          % (added, rejected, len(approved["quotes"])))


def main():
    for a in sys.argv[1:]:
        if a.startswith("--export="):
            export(int(a.split("=", 1)[1]))
            return 0
        if a.startswith("--import="):
            import_marks(int(a.split("=", 1)[1]))
            return 0
    print("Использование: python approval.py --export=N | --import=N")
    return 1


if __name__ == "__main__":
    sys.exit(main())
