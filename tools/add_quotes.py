# -*- coding: utf-8 -*-
"""Нормализация и проверка текста фразы для ролика.

Сравнение фраз идёт по нормализованному тексту: без регистра, пунктуации и ё/е,
поэтому «Не жди момента» и «не жди момента!» считаются одним и тем же.
"""

import re

MAX_WORDS = 12


def normalize(text):
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def lint(text):
    """Типовые огрехи: нет знака в конце, длина, латиница, короткое тире, мужской род в обращении."""
    problems = []
    if not text.endswith((".", "!", "?", "…")):
        problems.append("нет знака в конце — голос не сделает паузу")
    words = len(text.split())
    if words < 2:
        problems.append("слишком короткая фраза")
    if words > MAX_WORDS:
        problems.append("длиннее %d слов" % MAX_WORDS)
    if re.search(r"[a-zA-Z]", text):
        problems.append("латиница в русском тексте")
    if re.search(r"\s{2,}", text):
        problems.append("двойные пробелы")
    if re.search(r"\s[-–]\s", text):
        problems.append("короткое тире вместо длинного")
    if re.search(r"\bты\s+(не\s+)?\w+(л|лся)\b", text, re.I):
        problems.append("мужской род в обращении: «ты …л»")
    return problems
