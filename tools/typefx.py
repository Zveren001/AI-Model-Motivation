# -*- coding: utf-8 -*-
"""Девять анимаций текста из первых роликов канала, привязанные к голосу.

Эффекты перенесены из старого reel.py: шрифт Constantine, та же раскладка,
курсор, отскок, шторка и ореол. Вспышку с инверсией убрали после
утверждения: поверх видео она на миг заливала весь фон белым. Раньше они шли по своему
таймеру, теперь каждое слово появляется, когда его произносят, и пауза
в речи становится паузой в печати. Кадр рисуется на прозрачном слое,
видеофон под него подкладывает ffmpeg.
"""

import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import config

W, H = 1080, 1920
MARGIN = 110
BLOCK_H = 900
MAX_LINES = 6
LINE_RATIO = 1.32
FONT_PATH = os.path.join(config.ROOT, "assets", "fonts", "Constantine.ttf")
TEXT = (255, 255, 255)
GLOW = (255, 206, 128)

# Стук клавиш уместен только там, где буквы печатаются по одной: под слова
# и строки, появляющиеся целиком, он звучит лишним — так решили на утверждении
CLICK_EFFECTS = {"pechat_posimvolno", "pechat_s_podsvetkoj"}

NAMES = {
    "pechat_posimvolno": "печать по буквам",
    "pechat_slovami": "печать словами",
    "pechat_strokami": "печать строками",
    "slova_proyavlyayutsya": "слова проявляются",
    "slova_snizu": "слова снизу",
    "shtorka_po_strokam": "шторка",
    "slova_padayut": "слова падают",
    "pechat_s_podsvetkoj": "печать с ореолом",
    "slova_vspyshkoj": "слова вспышкой",
}

_fonts = {}


def font(size):
    if size not in _fonts:
        _fonts[size] = ImageFont.truetype(FONT_PATH, size)
    return _fonts[size]


def ease_out(t):
    return 1 - (1 - t) ** 3


def clamp(value):
    return max(0.0, min(1.0, value))


SHORT_WORDS = set("""
не ни и а но да или что чтобы как в во на с со к ко по до от за о об у из
для при без под над про же ли бы потому лишь
""".split())
SOFT_WORDS = set("""
то это ты мы я он она его её их мой твой свой так там где когда если чем
кто тот та те все всё уже ещё тоже только самому самой
""".split())
SENTENCE_END = ".!?…"
CLAUSE_END = ",;:"
DASHES = "—–"
SIZE_PENALTY = 0.035
MIN_READABLE = 68


def token_core(token):
    return "".join(ch for ch in token.lower() if ch.isalpha()).replace("ё", "е")


def line_cost(tokens, width, box, last_line, first_line=False):
    """Цена строки: пустота справа, конец на знаке — хорошо, на «не» или «что» — плохо."""
    slack = (box - width) / box
    cost = slack * slack * (0.5 if last_line else 3.0)
    if any(t.rstrip("»")[-1:] in SENTENCE_END for t in tokens[:-1]):
        cost += 1.0
    if len(tokens) == 1 and not (first_line and last_line):
        short = len(token_core(tokens[0])) <= 3
        if short:
            cost += 1.5
        elif not last_line:
            cost += 0.9
    if not last_line:
        end = tokens[-1].rstrip("»")[-1:]
        opened = any(t.rstrip("»")[-1:] in CLAUSE_END + DASHES for t in tokens[:-1])
        if opened and end not in SENTENCE_END + CLAUSE_END:
            cost += 0.7
        if end in SENTENCE_END:
            cost -= 1.5
        elif end in CLAUSE_END:
            cost -= 0.8
        elif end in DASHES:
            cost -= 0.3
        elif token_core(tokens[-1]) in SHORT_WORDS:
            cost += 3.5
        elif token_core(tokens[-1]) in SOFT_WORDS:
            cost += 0.8
    return cost


class Layout(object):
    """Раскладка цитаты: кегль, строки из слов и координаты каждого слова."""

    def __init__(self, tokens, sizes=range(104, 47, -2), center=0.5):
        probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        self.probe = probe
        box = W - MARGIN * 2
        options = []
        for size in sizes:
            cost, lines = self.wrap(tokens, font(size), box)
            if lines and int(size * LINE_RATIO) * len(lines) <= BLOCK_H:
                crowded = max(0, len(lines) - 4) * 0.8
                options.append((cost + crowded + (sizes[0] - size) * SIZE_PENALTY, size, lines))
        readable = [o for o in options if o[1] >= MIN_READABLE]
        if readable or options:
            _, size, lines = min(readable or options)
        else:
            size = min(sizes)
            lines = self.wrap(tokens, font(size), box * 2)[1]
        self.font = font(size)
        self.lines = lines
        self.line_height = int(size * LINE_RATIO)
        self.top = int(H * center - self.line_height * len(lines) / 2)
        self.strings = [" ".join(line) for line in lines]
        self.widths = [probe.textlength(s, font=self.font) for s in self.strings]
        self.slots, self.spans = [], []
        offset = 0
        for i, line in enumerate(lines):
            x, y = self.line_xy(i)
            inner = 0
            for token in line:
                self.slots.append((x, y, token, i))
                self.spans.append((offset + inner, offset + inner + len(token)))
                x += probe.textlength(token + " ", font=self.font)
                inner += len(token) + 1
            offset += len(self.strings[i])

    def wrap(self, tokens, face, box):
        """Смысловые переносы: из всех раскладок по ширине — самая дешёвая по line_cost."""
        n = len(tokens)
        best = [(0.0, [])] + [(None, None)] * n
        for j in range(1, n + 1):
            for i in range(j - 1, -1, -1):
                width = self.probe.textlength(" ".join(tokens[i:j]), font=face)
                if width > box:
                    break
                if best[i][0] is None or len(best[i][1]) >= MAX_LINES:
                    continue
                cost = best[i][0] + 0.45 + line_cost(tokens[i:j], width, box, j == n, i == 0)
                if j == n and j - i == 1 and len(best[i][1]) >= 3:
                    cost += 0.5
                if best[j][0] is None or cost < best[j][0]:
                    best[j] = (cost, best[i][1] + [tokens[i:j]])
        return best[n] if best[n][0] is not None else (0.0, [])

    def line_xy(self, index):
        return (W - self.widths[index]) / 2, self.top + index * self.line_height

    def width_of(self, text):
        return self.probe.textlength(text, font=self.font)


class Timeline(object):
    """Когда звучит каждое слово цитаты; для печати — когда появляется каждая буква."""

    def __init__(self, starts, ends):
        self.starts, self.ends = starts, ends
        self.speech_end = ends[-1] if ends else 0.0

    def chars(self, layout, t):
        shown = 0
        for (a, b), s, e in zip(layout.spans, self.starts, self.ends):
            if t >= e:
                shown = max(shown, b)
            elif t >= s:
                shown = max(shown, a + int(round((b - a) * (t - s) / max(0.05, e - s))))
        return shown

    def words(self, t):
        return sum(1 for s in self.starts if s <= t)

    def line_range(self, layout, index):
        members = [k for k, slot in enumerate(layout.slots) if slot[3] == index]
        return self.starts[members[0]], self.ends[members[-1]]


def visible_prefix(lines, count):
    out, left = [], count
    for line in lines:
        if left <= 0:
            out.append("")
            continue
        out.append(line[:left])
        left -= len(line)
    return out


def layer():
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))


def cursor_at(layout, draw, x, y, colour=TEXT):
    h = layout.font.size
    draw.rectangle([x + 6, y + h * 0.18, x + 6 + max(6, h // 12), y + h * 1.02],
                   fill=colour + (255,))


def draw_lines(layout, draw, lines, colour=TEXT, alpha=255):
    for i, line in enumerate(lines):
        if line:
            draw.text(layout.line_xy(i), line, font=layout.font, fill=colour + (alpha,))


def typed(layout, timeline, t, draw, colour=TEXT, cursor=True):
    shown = visible_prefix(layout.strings, timeline.chars(layout, t))
    draw_lines(layout, draw, shown, colour)
    if cursor and any(shown) and int(t * 2) % 2 == 0:
        idx = max(i for i, l in enumerate(shown) if l)
        x, y = layout.line_xy(idx)
        cursor_at(layout, draw, x + layout.width_of(shown[idx]), y, colour)


def eff_type_char(layout, timeline, t, frame):
    """Печать посимвольно с мигающим курсором."""
    typed(layout, timeline, t, ImageDraw.Draw(frame))


def eff_type_word(layout, timeline, t, frame):
    """Печать целыми словами: слово возникает разом, обрубков не бывает."""
    shown = timeline.words(t)
    draw = ImageDraw.Draw(frame)
    for x, y, word, _ in layout.slots[:shown]:
        draw.text((x, y), word, font=layout.font, fill=TEXT + (255,))
    if shown and int(t * 2) % 2 == 0:
        x, y, word, _ = layout.slots[shown - 1]
        cursor_at(layout, draw, x + layout.width_of(word), y)


def eff_type_line(layout, timeline, t, frame):
    """Строки выкладываются целиком, одна за другой."""
    count = sum(1 for i in range(len(layout.lines))
                if timeline.line_range(layout, i)[0] <= t)
    lines = list(layout.strings[:count]) + [""] * (len(layout.lines) - count)
    draw_lines(layout, ImageDraw.Draw(frame), lines)


def eff_fade_words(layout, timeline, t, frame):
    """Слова проявляются по очереди прозрачностью."""
    draw = ImageDraw.Draw(frame)
    for (x, y, word, _), s in zip(layout.slots, timeline.starts):
        a = int(255 * clamp((t - s) / 0.45))
        if a:
            draw.text((x, y), word, font=layout.font, fill=TEXT + (a,))


def eff_rise_words(layout, timeline, t, frame):
    """Слова выезжают снизу и садятся на место."""
    draw = ImageDraw.Draw(frame)
    for (x, y, word, _), s in zip(layout.slots, timeline.starts):
        local = clamp((t - s) / 0.5)
        if local > 0:
            draw.text((x, y + (1 - ease_out(local)) * 55), word, font=layout.font,
                      fill=TEXT + (int(255 * local),))


def eff_wipe_lines(layout, timeline, t, frame):
    """Строки открываются шторкой слева направо."""
    text = layer()
    draw_lines(layout, ImageDraw.Draw(text), layout.strings)
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    for i in range(len(layout.lines)):
        s, e = timeline.line_range(layout, i)
        local = clamp((t - s) / max(0.35, e - s))
        if local <= 0:
            continue
        x, y = layout.line_xy(i)
        md.rectangle([x - 10, y - 10, x + layout.widths[i] * ease_out(local) + 10,
                      y + layout.line_height], fill=255)
    text.putalpha(Image.composite(text.split()[3], Image.new("L", (W, H), 0), mask))
    frame.alpha_composite(text)


def eff_drop_words(layout, timeline, t, frame):
    """Слова падают сверху с лёгким отскоком."""
    draw = ImageDraw.Draw(frame)
    for (x, y, word, _), s in zip(layout.slots, timeline.starts):
        local = clamp((t - s) / 0.42)
        if local <= 0:
            continue
        e = ease_out(local)
        bounce = 14 * (1 - e) if local > 0.75 else 0
        draw.text((x, y - (1 - e) * 120 + bounce), word, font=layout.font,
                  fill=TEXT + (int(255 * min(1.0, local * 1.6)),))


def eff_type_glow(layout, timeline, t, frame):
    """Печать, затем пульсирующий ореол вокруг последнего слова."""
    start = timeline.speech_end + 0.1
    if t >= start:
        x, y, word, _ = layout.slots[-1]
        pad = layout.font.size
        width = int(layout.width_of(word))
        box = (int(x - pad), int(y - pad), int(x + width + pad), int(y + pad * 2.4))
        glow = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), (0, 0, 0, 0))
        pulse = abs(((t - start) % 1.4) / 1.4 - 0.5) * 2
        ink = GLOW + (int(255 * (0.45 + 0.55 * pulse)),)
        ImageDraw.Draw(glow).text((pad, pad), word, font=layout.font, fill=ink,
                                  stroke_width=max(6, layout.font.size // 9), stroke_fill=ink)
        frame.alpha_composite(glow.filter(ImageFilter.GaussianBlur(18)), (box[0], box[1]))
    typed(layout, timeline, t, ImageDraw.Draw(frame), cursor=t < start)


def eff_scale_pop(layout, timeline, t, frame):
    """Слова вспыхивают крупнее и садятся в размер."""
    draw = ImageDraw.Draw(frame)
    for (x, y, word, _), s in zip(layout.slots, timeline.starts):
        local = clamp((t - s) / 0.38)
        if local <= 0:
            continue
        k = 1.0 + 0.35 * (1 - ease_out(local))
        size = max(8, int(layout.font.size * k))
        face = font(size)
        shift = (layout.probe.textlength(word, font=face) - layout.width_of(word)) / 2
        draw.text((x - shift, y - (size - layout.font.size) * 0.55), word, font=face,
                  fill=TEXT + (int(255 * local),))


EFFECTS = {
    "pechat_posimvolno": eff_type_char,
    "pechat_slovami": eff_type_word,
    "pechat_strokami": eff_type_line,
    "slova_proyavlyayutsya": eff_fade_words,
    "slova_snizu": eff_rise_words,
    "shtorka_po_strokam": eff_wipe_lines,
    "slova_padayut": eff_drop_words,
    "pechat_s_podsvetkoj": eff_type_glow,
    "slova_vspyshkoj": eff_scale_pop,
}
ORDER = tuple(EFFECTS)


def frame_at(effect, layout, timeline, t):
    """Кадр текстового слоя в момент t на прозрачном фоне."""
    frame = layer()
    EFFECTS[effect](layout, timeline, t, frame)
    return frame
