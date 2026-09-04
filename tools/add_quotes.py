# -*- coding: utf-8 -*-
"""Добавление цитат в базу с проверкой на дубли и работа с базой.

Сравнение идёт по нормализованному тексту: без регистра, пунктуации и ё/е,
поэтому «Не жди момента» и «не жди момента!» считаются одним и тем же.

К цитате можно прикрепить крючок, рассуждение и вопрос зрителю: из таких
цитат собираются развёрнутые ролики. Обычные цитаты идут в картинки
и короткие ролики.
"""

import json
import os
import re
import sys

import config

JOURNAL = os.path.join(config.ROOT, "post_log.json")

HOOK_MAX = 60
REASONING_MAX = 200
ACTION_MAX = 110
QUESTION_MAX = 80
SPEECH_MAX_WORDS = 50


def normalize(text):
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


SUSPICIOUS = [
    (r"значит(?!,)(?=[^,]*$)", "«значит» как вводное слово требует запятых"),
    (r"^[А-ЯЁ][а-яё]+ (это|не) ", None),
    (r"\s(и|а|но|или)\s*$", "обрывается на союзе"),
    (r"[a-zA-Z]", "латиница в русском тексте"),
    (r"\s{2,}", "двойные пробелы"),
    (r"[.!?]$", "точка или знак в конце — в этом проекте не ставятся"),
    (r"чья-то(?=\s+(ожидание|решение|дело))", "рассогласование рода"),
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


def lint_long(entry):
    """Проверка развёртки: длина под речь и форма каждой части."""
    problems = []
    hook, reasoning = entry["hook"], entry["reasoning"]
    action, question = entry["action"], entry["question"]
    if len(hook) > HOOK_MAX:
        problems.append("крючок длиннее %d символов" % HOOK_MAX)
    if not hook.endswith((".", "?", "!")):
        problems.append("крючок без знака в конце — озвучка не сделает паузу")
    if len(reasoning) > REASONING_MAX:
        problems.append("объяснение длиннее %d символов" % REASONING_MAX)
    if not reasoning.endswith("."):
        problems.append("объяснение без точки в конце")
    if len(action) > ACTION_MAX:
        problems.append("совет длиннее %d символов" % ACTION_MAX)
    if not action.endswith("."):
        problems.append("совет без точки в конце")
    if len(question) > QUESTION_MAX:
        problems.append("вопрос длиннее %d символов" % QUESTION_MAX)
    if not question.endswith("?"):
        problems.append("вопрос без знака вопроса")
    words = len(" ".join([hook, reasoning, action, question]).split())
    if words > SPEECH_MAX_WORDS:
        problems.append("речь длиннее %d слов: %d" % (SPEECH_MAX_WORDS, words))
    if re.search(r"[a-zA-Z]", hook + reasoning + action + question):
        problems.append("латиница в русском тексте")
    return problems


def load():
    if not os.path.exists(config.QUOTES):
        return {"quotes": []}
    with open(config.QUOTES, encoding="utf-8") as f:
        return json.load(f)


def save(data):
    with open(config.QUOTES, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_long(quote):
    return all(quote.get(k) for k in ("hook", "reasoning", "action", "question"))


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


def extend(entries, verbose=True):
    """Прикрепляет к цитатам по id крючок, объяснение, совет и вопрос для ролика.

    entries — список словарей с ключами id, hook, reasoning, action, question;
    необязательный text заменяет саму цитату, если старая звучала избито.
    Использованную цитату трогать бессмысленно, она пропускается.
    """
    data = load()
    by_id = {q["id"]: q for q in data["quotes"]}
    done, skipped = 0, 0
    for entry in entries:
        quote = by_id.get(entry["id"])
        if not quote:
            print("  нет цитаты #%s" % entry["id"])
            skipped += 1
            continue
        if quote.get("used"):
            print("  цитата #%d уже использована, пропускаю" % entry["id"])
            skipped += 1
            continue
        issues = lint_long(entry)
        if issues and verbose:
            print("  проверь #%d: %s" % (entry["id"], quote["text"]))
            for i in issues:
                print("     %s" % i)
        if entry.get("text"):
            quote["text"] = entry["text"].strip().rstrip(".")
        for key in ("hook", "reasoning", "action", "question"):
            quote[key] = entry[key].strip()
        done += 1

    save(data)
    if verbose:
        total = sum(1 for q in data["quotes"] if is_long(q))
        print("развёрнуто: %d, пропущено: %d, всего с рассуждением: %d"
              % (done, skipped, total))
    return done


def strip(ids, verbose=True):
    """Снимает развёртку с цитат по id: они возвращаются в пул для картинок."""
    data = load()
    count = 0
    for q in data["quotes"]:
        if q["id"] in set(ids):
            for key in ("hook", "reasoning", "action", "question"):
                q.pop(key, None)
            count += 1
    save(data)
    if verbose:
        print("развёртка снята: %d" % count)
    return count


def remove(ids, verbose=True):
    """Убирает цитаты по id — для кривых текстов, найденных при вычитке."""
    data = load()
    wanted = set(ids)
    kept = [q for q in data["quotes"] if q["id"] not in wanted]
    gone = len(data["quotes"]) - len(kept)
    data["quotes"] = kept
    save(data)
    if verbose:
        print("удалено: %d, всего в базе: %d" % (gone, len(kept)))
    return gone


def sync_used():
    """Переносит отметки использования из журнала публикаций в базу.

    Нужно на сервере после git pull: база в git приходит с чистыми флагами,
    а какие цитаты уже вышли, знает только журнал.
    """
    if not os.path.exists(JOURNAL):
        print("Журнал %s не найден" % JOURNAL)
        return 0
    with open(JOURNAL, encoding="utf-8") as f:
        posts = json.load(f).get("posts", {})
    data = load()
    by_id = {q["id"]: q for q in data["quotes"]}
    marked = 0
    for post in posts.values():
        quote = by_id.get(post.get("quote_id"))
        if quote and not quote.get("used"):
            quote["used"] = True
            quote["used_at"] = post.get("at")
            marked += 1
    save(data)
    used = sum(1 for q in data["quotes"] if q.get("used"))
    print("отмечено по журналу: %d, всего использовано: %d из %d"
          % (marked, used, len(data["quotes"])))
    return marked


def lint_all():
    """Прогоняет всю базу через проверку — для контроля после правок."""
    data = load()
    flagged = 0
    for q in data["quotes"]:
        issues = lint(q["text"])
        if is_long(q):
            issues += lint_long(q)
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
    long_left = sum(1 for q in quotes if is_long(q) and not q.get("used"))
    topics = {}
    for q in quotes:
        topics[q["topic"]] = topics.get(q["topic"], 0) + 1

    print("всего цитат: %d" % len(quotes))
    print("использовано: %d, осталось: %d" % (used, len(quotes) - used))
    print("с рассуждением осталось: %d — хватит на %d дней при одном развёрнутом ролике в сутки"
          % (long_left, long_left))
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
    elif "--sync-used" in sys.argv:
        sync_used()
    else:
        print("Модуль для работы с базой цитат.")
        print("  --stats      статистика базы")
        print("  --lint       проверка текстов")
        print("  --sync-used  отметить использованные по журналу (на сервере после git pull)")
