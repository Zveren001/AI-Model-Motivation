# -*- coding: utf-8 -*-
"""Цитата, загорающаяся в ритм речи, и призыв в конце — формат ASS.

Цитата стоит в кадре целиком с нулевой секунды: непроизнесённые слова
приглушены, произнесённое загорается белым. У ролика нет пустого начала,
зритель видит мысль сразу, а голос ведёт по ней.

Каждое слово выводится своим событием с абсолютной позицией, поэтому
момент загорания можно оформить по-разному: слово просто загорается,
выезжает снизу, вспыхивает крупнее, светится или загорается вместе
со всей строкой. Эффект идёт по кругу и пишется в журнал — дальше
статистика скажет, какой держит зрителя.

Последние события гасят цитату обратно в приглушённую, поэтому финальный
кадр совпадает с первым и повтор в ленте склеивается без рывка.
"""

import os
import re

from PIL import ImageFont

import config

WIDTH, HEIGHT = 1080, 1920
MARGIN = 90
BLOCK_H = 1000
MAX_LINES = 5

FONT = "Roboto"
FONT_FILE = os.path.join(config.ROOT, "assets", "fonts", "Roboto-Bold.ttf")
SIZE_MAX, SIZE_MIN, LINE_RATIO = 136, 72, 1.30

# Кегль в ASS и в Pillow — разные вещи: libass рисует ровно три четверти
# от ширины, которую даёт Pillow тем же числом. Замер сделан на обеих
# машинах, локальной и серверной, и совпал до пикселя. Без поправки
# координаты слов разъезжаются, а строки выходят мельче задуманного.
SCALE = 0.75

CTA_SIZE = 56
CTA_MARGIN_V = 300

BRIGHT = r"\alpha&H00&"
DIM = r"\alpha&H78&"
FADE_BACK = 450

# Чем оформлен момент, когда слово произносят. Пятый эффект отличается
# не оформлением, а таймингом: слова строки загораются разом.
EFFECTS = {
    "zagoranie": r"\fad(90,0)",
    "slova_snizu": r"\fad(120,0)\move(%(x).0f,%(y_from).0f,%(x).0f,%(y).0f,0,220)",
    "slova_vspyshkoj": r"\fad(70,0)\fscx112\fscy112\t(0,190,\fscx100\fscy100)",
    "podsvetka": r"\fad(80,0)\blur7\t(0,280,\blur0)",
    "stroki_zagorayutsya": r"\fad(140,0)",
}
EFFECT_ORDER = ("zagoranie", "slova_snizu", "slova_vspyshkoj",
                "podsvetka", "stroki_zagorayutsya")
RISE = 32

STYLES = [
    ("Quote", SIZE_MAX, 7, 4, 5, 0),
    ("Cta", CTA_SIZE, 4, 2, 2, CTA_MARGIN_V),
]

_fonts = {}


def font(size):
    if size not in _fonts:
        _fonts[size] = ImageFont.truetype(FONT_FILE, size)
    return _fonts[size]


def clean(text):
    text = re.sub(r"[.,;:!?…«»\"]", "", text)
    return re.sub(r"\s+", " ", text).strip().upper()


def width_of(text, size):
    """Ширина текста в кадре, как её нарисует libass."""
    return font(size).getlength(text) * SCALE


def line_height(size):
    return size * SCALE * LINE_RATIO


def wrap(words, size):
    """Разбивает слова на строки по ширине кадра."""
    limit = WIDTH - 2 * MARGIN
    lines, current = [], []
    for word in words:
        probe = current + [word]
        if current and width_of(" ".join(probe), size) > limit:
            lines.append(current)
            current = [word]
        else:
            current = probe
    if current:
        lines.append(current)
    return lines


def layout(words):
    """Кегль и строки, при которых цитата целиком помещается в кадр."""
    for size in range(SIZE_MAX, SIZE_MIN - 1, -4):
        lines = wrap(words, size)
        if len(lines) <= MAX_LINES and len(lines) * line_height(size) <= BLOCK_H:
            if max(width_of(" ".join(l), size) for l in lines) <= WIDTH - 2 * MARGIN:
                return size, lines
    return SIZE_MIN, wrap(words, SIZE_MIN)


def positions(lines, size):
    """Центр каждого слова: строки центрированы, слова идут подряд с пробелом."""
    line_h = line_height(size)
    top = (HEIGHT - line_h * len(lines)) / 2
    space = width_of(" ", size)
    out = []
    for row, line in enumerate(lines):
        x = (WIDTH - width_of(" ".join(line), size)) / 2
        y = top + line_h * row + line_h / 2
        for word in line:
            width = width_of(word, size)
            out.append((x + width / 2, y))
            x += width + space
    return out


def line_starts(lines, starts):
    """Тайминги, при которых вся строка загорается на своём первом слове."""
    out, index = [], 0
    for line in lines:
        first = starts[index]
        for _ in line:
            out.append(first)
            index += 1
    return out


def stamp(seconds):
    seconds = max(0.0, seconds)
    return "%d:%02d:%05.2f" % (int(seconds // 3600), int(seconds % 3600 // 60),
                               seconds % 60)


def header(size):
    lines = [
        "[Script Info]", "ScriptType: v4.00+",
        "PlayResX: %d" % WIDTH, "PlayResY: %d" % HEIGHT, "WrapStyle: 2", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    ]
    for name, base, outline, shadow, align, margin_v in STYLES:
        lines.append("Style: %s,%s,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,"
                     "1,0,0,0,100,100,0,0,1,%d,%d,%d,%d,%d,%d,1"
                     % (name, FONT, size if name == "Quote" else base,
                        outline, shadow, align, MARGIN, MARGIN, margin_v))
    lines += ["", "[Events]",
              "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    return lines


def event(start, end, style, tags, text, layer=0):
    return "Dialogue: %d,%s,%s,%s,,0,0,0,,{%s}%s" % (layer, stamp(start), stamp(end),
                                                     style, tags, text)


def at(x, y):
    return r"\an5\pos(%.0f,%.0f)" % (x, y)


def lit_tags(effect, x, y):
    """Теги загоревшегося слова: позиция, полная яркость и оформление момента."""
    shape = EFFECTS[effect] % {"x": x, "y": y, "y_from": y + RISE}
    if "move" in shape:
        return r"\an5" + shape + BRIGHT
    return at(x, y) + shape + BRIGHT


def write(words, cta, duration, out_path, effect="zagoranie"):
    """Пишет ASS: слова цитаты загораются по таймингам речи, в конце призыв.

    words — [(начало, конец, слово)] по цитате, cta — (начало, конец, текст)
    или None. Возвращает кегль и число строк.
    """
    if effect not in EFFECTS:
        effect = "zagoranie"
    plain = [clean(w) for _, _, w in words]
    size, lines = layout(plain)
    spots = positions(lines, size)
    flat = [w for line in lines for w in line]

    starts = [start for start, _, _ in words]
    if effect == "stroki_zagorayutsya":
        starts = line_starts(lines, starts)

    quote_end = cta[0] if cta else duration - FADE_BACK / 1000.0
    out = header(size)

    # Приглушённое слово лежит нижним слоем всю дорогу, загоревшееся ложится
    # поверх: иначе слово, которое выезжает снизу, на время полёта исчезает
    # со своего места и это читается как мигание
    for i, word in enumerate(flat):
        x, y = spots[i]
        out.append(event(0.0, quote_end, "Quote", at(x, y) + DIM, word))
        out.append(event(starts[i], quote_end, "Quote",
                         lit_tags(effect, x, y), word, layer=1))

    if cta:
        cta_start, cta_end, cta_text = cta
        for i, word in enumerate(flat):
            x, y = spots[i]
            out.append(event(cta_start, cta_end, "Quote", at(x, y) + BRIGHT, word, layer=1))
        out.append(event(cta_start, cta_end, "Cta",
                         r"\alpha&H20&\fad(220,180)", clean(cta_text)))
        quote_end = cta_end

    # Возврат к приглушённой цитате: последний кадр совпадает с первым,
    # и повтор ролика в ленте склеивается без рывка
    for i, word in enumerate(flat):
        x, y = spots[i]
        out.append(event(quote_end, duration, "Quote",
                         at(x, y) + BRIGHT + r"\t(0,%d,%s)" % (FADE_BACK, DIM), word))

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    return size, len(lines)
