# -*- coding: utf-8 -*-
"""Субтитры в ритм речи: группы по два-четыре слова в формате ASS.

Группа держится на экране до появления следующей, поэтому пустых кадров
нет: первая группа стоит с нулевого кадра, последняя — до конца ролика.
Граница группы — конец предложения, заметная пауза в речи или три слова,
но группа не заканчивается на предлоге, союзе или частице: «растёт от» /
«неясности» читается как обрыв.

Переносы строк считаются здесь, по ширине шрифта, а автоперенос libass
выключен: иначе анимация появления, которая растит текст с 94 до 100 %,
меняла бы ширину и перекладывала строку на ходу — фраза мелькала бы дважды.
"""

import os
import re

from PIL import ImageFont

import config

WIDTH, HEIGHT = 1080, 1920
MARGIN = 70
MAX_WORDS = 3
HARD_MAX_WORDS = 5
PAUSE_BREAK = 0.45
FONT = "Roboto"
FONT_FILE = os.path.join(config.ROOT, "assets", "fonts", "Roboto-Bold.ttf")
FONT_SIZE = 118
LINE_FILL = 0.94
STYLE = ("Style: Words,%s,%d,&H00FFFFFF,&H00FFFFFF,&H96000000,&H8C000000,"
         "1,0,0,0,100,100,1,0,1,6,4,5,%d,%d,0,1" % (FONT, FONT_SIZE, MARGIN, MARGIN))
POP = r"\fad(60,0)\fscx94\fscy94\t(0,90,\fscx100\fscy100)"

STOP = set("""
не ни в во на с со к ко по до от за о об у из для при без под над про через
и а но или что чтобы как ты я мы вы он она они это то же бы ли уже ещё еще
так там где когда если пока чем тем кто свой твой твоя твоё твое свою своё свое
его её ее их мой моя моё самый самое каждый каждое один одно одна два две три
пять десять двадцать только просто очень почти даже тоже всего этой этого этом
эту этим того тот та те какой какая какое какую сколько
""".split())

_font = None


def font():
    global _font
    if _font is None:
        _font = ImageFont.truetype(FONT_FILE, FONT_SIZE)
    return _font


def width_of(text):
    return font().getlength(text)


def attach_punctuation(words, script):
    """Возвращает словам знаки препинания из исходного текста.

    Сервис отдаёт слова голыми, а конец предложения нужен для разбивки
    на группы. Слово ищется среди ближайших трёх токенов текста, чтобы
    одно расхождение не сбило все остальные.
    """
    tokens = script.split()
    out, j = [], 0
    for start, end, word in words:
        core = re.sub(r"[^\w-]", "", word).lower()
        found = None
        for k in range(j, min(j + 3, len(tokens))):
            if re.sub(r"[^\w-]", "", tokens[k]).lower() == core:
                found = k
                break
        if found is None:
            out.append((start, end, word))
        else:
            out.append((start, end, tokens[found]))
            j = found + 1
    return out


def clean(text):
    text = re.sub(r"[.,;:!?…«»\"]", "", text)
    return text.upper()


def group_words(words):
    """Режет слова на группы: (начало, конец, текст)."""
    groups, current = [], []
    for i, (start, end, word) in enumerate(words):
        current.append((start, end, word))
        core = clean(word).lower()
        sentence_end = bool(re.search(r"[.!?…]$", word))
        pause = i + 1 < len(words) and words[i + 1][0] - end > PAUSE_BREAK
        full = len(current) >= MAX_WORDS and core not in STOP
        if sentence_end or pause or full or len(current) >= HARD_MAX_WORDS:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return [(g[0][0], g[-1][1], " ".join(w for _, _, w in g)) for g in groups]


def split_lines(text):
    """Строки группы по ширине шрифта: одна, две или три, самые ровные."""
    words = text.split()
    limit = (WIDTH - 2 * MARGIN) * LINE_FILL
    if width_of(text) <= limit or len(words) == 1:
        return [text]
    best = None
    for count in (2, 3):
        if len(words) < count:
            break
        for cut in _cuts(len(words), count):
            lines = [" ".join(words[a:b]) for a, b in zip((0,) + cut, cut + (len(words),))]
            widest = max(width_of(l) for l in lines)
            if best is None or widest < best[0]:
                best = (widest, lines)
        if best and best[0] <= limit:
            return best[1]
    return best[1] if best else [text]


def _cuts(n, count):
    """Все способы разрезать n слов на count непустых строк."""
    if count == 2:
        return [(k,) for k in range(1, n)]
    return [(a, b) for a in range(1, n - 1) for b in range(a + 1, n)]


def fit_size(lines):
    """Кегль, при котором самая широкая строка помещается в кадр."""
    limit = WIDTH - 2 * MARGIN
    widest = max(width_of(l) for l in lines)
    if widest <= limit:
        return FONT_SIZE
    return int(FONT_SIZE * limit / widest)


def stamp(seconds):
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return "%d:%02d:%05.2f" % (h, m, s)


def write(words, duration, out_path):
    """Пишет ASS-файл: каждая группа держится до начала следующей."""
    groups = group_words(words)
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: %d" % WIDTH,
        "PlayResY: %d" % HEIGHT,
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        STYLE,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for i, (start, _, text) in enumerate(groups):
        begin = 0.0 if i == 0 else start
        finish = groups[i + 1][0] if i + 1 < len(groups) else duration
        rows = split_lines(clean(text))
        tags = r"\q2"
        size = fit_size(rows)
        if size != FONT_SIZE:
            tags += r"\fs%d" % size
        # Первая группа без плавного появления: иначе нулевой кадр, из которого
        # YouTube берёт обложку, остаётся без текста
        if i:
            tags += POP
        lines.append("Dialogue: 0,%s,%s,Words,,0,0,0,,{%s}%s"
                     % (stamp(begin), stamp(finish), tags, r"\N".join(rows)))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return groups
