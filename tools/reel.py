# -*- coding: utf-8 -*-
"""Сборка вертикального ролика с цитатой.

Кадры рисуются тем же шрифтом и в той же палитре, что квадратные картинки,
но в формате 1080x1920. Раскладка строк считается один раз по полному тексту,
а эффект лишь раскрывает уже размеченные слова: иначе строки перескакивали бы
на каждом новом слове.

Звук берётся из assets/audio: дорожка подбирается под тему кадра, а к эффектам
с печатью подмешивается стук клавиш.
"""

import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import config

W, H = 1080, 1920
FPS = 30
DURATION = 7.0
MARGIN = 110
BLOCK_H = 900

AUDIO_DIR = os.path.join(config.ROOT, "assets", "audio")
FONT_PATH = os.path.join(config.ROOT, "assets", "fonts",
                         config.get("FONT", "Constantine.ttf"))

WHITE = ((255, 255, 255), (17, 17, 17))
BLACK = ((17, 17, 17), (255, 255, 255))


def ffmpeg_bin():
    return config.get("FFMPEG", "ffmpeg")


def wrap(text, font, draw, max_width):
    words, lines, current = text.split(), [], ""
    for word in words:
        probe = (current + " " + word).strip()
        if draw.textlength(probe, font=font) <= max_width:
            current = probe
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def layout(text):
    """Кегль, строки и высота строки под вертикальный кадр."""
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    box = W - MARGIN * 2
    for size in range(104, 47, -2):
        font = ImageFont.truetype(FONT_PATH, size)
        lines = wrap(text, font, draw, box)
        line_height = int(size * 1.32)
        if line_height * len(lines) <= BLOCK_H and len(lines) <= 6:
            return font, lines, line_height
    font = ImageFont.truetype(FONT_PATH, 48)
    return font, wrap(text, font, draw, box), 64


def ease_out(t):
    return 1 - (1 - t) ** 3


def visible_prefix(lines, count):
    out, left = [], count
    for line in lines:
        if left <= 0:
            out.append("")
            continue
        out.append(line[:left])
        left -= len(line)
    return out


class Canvas(object):
    """Фон, раскладка текста и координаты строк и слов."""

    def __init__(self, text, theme):
        self.bg, self.fg = WHITE if theme == "white" else BLACK
        self.theme = theme
        self.text = text
        self.font, self.lines, self.line_height = layout(text)
        self.top = (H - self.line_height * len(self.lines)) // 2
        probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        self.widths = [probe.textlength(l, font=self.font) for l in self.lines]
        self.probe = probe

    def base(self):
        return Image.new("RGB", (W, H), self.bg)

    def layer(self):
        return Image.new("RGBA", (W, H), (0, 0, 0, 0))

    def line_xy(self, index):
        return (W - self.widths[index]) / 2, self.top + index * self.line_height

    def draw_lines(self, draw, lines, alpha=None):
        colour = self.fg + (alpha,) if alpha is not None else self.fg
        for i, line in enumerate(lines):
            if not line:
                continue
            x, y = self.line_xy(i)
            draw.text((x, y), line, font=self.font, fill=colour)

    def word_slots(self):
        """Слова с готовыми координатами.

        Считать позицию слова как длину предыдущих плюс пробел нельзя:
        на переносе строки пробела нет, счётчик убегает и режет слово пополам.
        """
        slots = []
        for i, line in enumerate(self.lines):
            x, y = self.line_xy(i)
            for word in line.split():
                slots.append((x, y, word))
                x += self.probe.textlength(word + " ", font=self.font)
        return slots

    def width_of(self, text):
        return self.probe.textlength(text, font=self.font)


def typing_progress(t, start=0.25, span=3.9):
    if t < start:
        return 0.0
    return min(1.0, (t - start) / span)


def cursor_at(canvas, draw, x, y):
    h = canvas.font.size
    draw.rectangle([x + 6, y + h * 0.18, x + 6 + max(6, h // 12), y + h * 1.02],
                   fill=canvas.fg)


def eff_type_char(canvas, t):
    """Печать посимвольно с мигающим курсором."""
    chars = sum(len(l) for l in canvas.lines)
    shown = visible_prefix(canvas.lines, int(typing_progress(t) * chars))
    frame = canvas.base()
    draw = ImageDraw.Draw(frame)
    canvas.draw_lines(draw, shown)
    if any(shown) and int(t * 2) % 2 == 0:
        idx = max(i for i, l in enumerate(shown) if l)
        x, y = canvas.line_xy(idx)
        cursor_at(canvas, draw, x + canvas.width_of(shown[idx]), y)
    return frame


def eff_type_word(canvas, t):
    """Печать целыми словами: слово возникает разом, обрубков не бывает."""
    slots = canvas.word_slots()
    shown = int(typing_progress(t, 0.2, 3.6) * len(slots) + 1e-6)
    frame = canvas.base()
    draw = ImageDraw.Draw(frame)
    for x, y, word in slots[:shown]:
        draw.text((x, y), word, font=canvas.font, fill=canvas.fg)
    if shown and int(t * 2) % 2 == 0:
        x, y, word = slots[shown - 1]
        cursor_at(canvas, draw, x + canvas.width_of(word), y)
    return frame


def eff_type_line(canvas, t):
    """Строки выкладываются целиком, одна за другой."""
    p = typing_progress(t, 0.2, 3.2)
    count = int(p * len(canvas.lines) + 1e-6)
    lines = list(canvas.lines[:count]) + [""] * (len(canvas.lines) - count)
    frame = canvas.base()
    canvas.draw_lines(ImageDraw.Draw(frame), lines)
    return frame


def eff_fade_words(canvas, t):
    """Слова проявляются по очереди прозрачностью."""
    slots = canvas.word_slots()
    step = 3.4 / max(1, len(slots))
    frame = canvas.base()
    layer = canvas.layer()
    draw = ImageDraw.Draw(layer)
    for i, (x, y, word) in enumerate(slots):
        a = int(255 * max(0.0, min(1.0, (t - 0.3 - i * step) / 0.45)))
        if a:
            draw.text((x, y), word, font=canvas.font, fill=canvas.fg + (a,))
    frame.paste(layer, (0, 0), layer)
    return frame


def eff_rise_words(canvas, t):
    """Слова выезжают снизу и садятся на место."""
    slots = canvas.word_slots()
    step = 3.2 / max(1, len(slots))
    frame = canvas.base()
    layer = canvas.layer()
    draw = ImageDraw.Draw(layer)
    for i, (x, y, word) in enumerate(slots):
        local = max(0.0, min(1.0, (t - 0.3 - i * step) / 0.5))
        if local > 0:
            shift = (1 - ease_out(local)) * 55
            draw.text((x, y + shift), word, font=canvas.font,
                      fill=canvas.fg + (int(255 * local),))
    frame.paste(layer, (0, 0), layer)
    return frame


def eff_wipe_lines(canvas, t):
    """Строки открываются шторкой слева направо."""
    frame = canvas.base()
    layer = canvas.layer()
    canvas.draw_lines(ImageDraw.Draw(layer), canvas.lines)
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    step = 3.0 / max(1, len(canvas.lines))
    for i in range(len(canvas.lines)):
        local = max(0.0, min(1.0, (t - 0.25 - i * step) / 0.6))
        if local <= 0:
            continue
        x, y = canvas.line_xy(i)
        md.rectangle([x - 10, y - 10, x + canvas.widths[i] * ease_out(local) + 10,
                      y + canvas.line_height], fill=255)
    layer.putalpha(Image.composite(layer.split()[3], Image.new("L", (W, H), 0), mask))
    frame.paste(layer, (0, 0), layer)
    return frame


def eff_type_invert(canvas, t):
    """Печать с короткой вспышкой инверсии на финале.

    Вспышка гаснет до конца ролика: последний кадр остаётся в своей теме,
    иначе белый пост показывал бы в ленте чёрную обложку.
    """
    chars = sum(len(l) for l in canvas.lines)
    shown = visible_prefix(canvas.lines, int(typing_progress(t, 0.25, 3.4) * chars))
    flipped = 4.25 <= t < 4.58
    bg, fg = (canvas.fg, canvas.bg) if flipped else (canvas.bg, canvas.fg)
    frame = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(frame)
    for i, line in enumerate(shown):
        if not line:
            continue
        x, y = canvas.line_xy(i)
        draw.text((x, y), line, font=canvas.font, fill=fg)
    if not flipped and any(shown) and int(t * 2) % 2 == 0:
        idx = max(i for i, l in enumerate(shown) if l)
        x, y = canvas.line_xy(idx)
        cursor_at(canvas, draw, x + canvas.width_of(shown[idx]), y)
    return frame


def eff_drop_words(canvas, t):
    """Слова падают сверху с лёгким отскоком."""
    slots = canvas.word_slots()
    step = 3.0 / max(1, len(slots))
    frame = canvas.base()
    layer = canvas.layer()
    draw = ImageDraw.Draw(layer)
    for i, (x, y, word) in enumerate(slots):
        local = max(0.0, min(1.0, (t - 0.25 - i * step) / 0.42))
        if local <= 0:
            continue
        e = ease_out(local)
        bounce = 14 * (1 - e) if local > 0.75 else 0
        draw.text((x, y - (1 - e) * 120 + bounce), word, font=canvas.font,
                  fill=canvas.fg + (int(255 * min(1.0, local * 1.6)),))
    frame.paste(layer, (0, 0), layer)
    return frame


def eff_type_glow(canvas, t):
    """Печать, затем пульсирующий ореол вокруг последнего слова."""
    chars = sum(len(l) for l in canvas.lines)
    p = typing_progress(t, 0.25, 3.3)
    shown = visible_prefix(canvas.lines, int(p * chars))
    frame = canvas.base()
    if p >= 1.0:
        last = len(canvas.lines) - 1
        word = canvas.lines[last].split()[-1]
        x, y = canvas.line_xy(last)
        x += canvas.width_of(canvas.lines[last][:-len(word)])
        glow = canvas.layer()
        pulse = abs(((t - 3.7) % 1.4) / 1.4 - 0.5) * 2
        ImageDraw.Draw(glow).text((x, y), word, font=canvas.font,
                                  fill=canvas.fg + (int(150 * pulse),))
        glow = glow.filter(ImageFilter.GaussianBlur(18))
        frame.paste(glow, (0, 0), glow)
    canvas.draw_lines(ImageDraw.Draw(frame), shown)
    return frame


def eff_scale_pop(canvas, t):
    """Слова вспыхивают крупнее и садятся в размер."""
    slots = canvas.word_slots()
    step = 3.0 / max(1, len(slots))
    frame = canvas.base()
    for i, (x, y, word) in enumerate(slots):
        local = max(0.0, min(1.0, (t - 0.25 - i * step) / 0.38))
        if local <= 0:
            continue
        k = 1.0 + 0.35 * (1 - ease_out(local))
        size = max(8, int(canvas.font.size * k))
        font = ImageFont.truetype(FONT_PATH, size)
        shift = (canvas.probe.textlength(word, font=font) - canvas.width_of(word)) / 2
        cell = canvas.layer()
        ImageDraw.Draw(cell).text((x - shift, y - (size - canvas.font.size) * 0.55),
                                  word, font=font, fill=canvas.fg + (int(255 * local),))
        frame.paste(cell, (0, 0), cell)
    return frame


EFFECTS = [
    ("pechat_posimvolno", eff_type_char, True),
    ("pechat_slovami", eff_type_word, True),
    ("pechat_strokami", eff_type_line, True),
    ("slova_proyavlyayutsya", eff_fade_words, False),
    ("slova_snizu", eff_rise_words, False),
    ("shtorka_po_strokam", eff_wipe_lines, False),
    ("pechat_s_inversiej", eff_type_invert, True),
    ("slova_padayut", eff_drop_words, False),
    ("pechat_s_podsvetkoj", eff_type_glow, True),
    ("slova_vspyshkoj", eff_scale_pop, False),
]


def effect_by_number(number):
    """Эффекты идут по кругу со сдвигом на каждом обороте.

    Без сдвига эффект навсегда сросся бы с одной темой: их десять,
    а тема чередуется через один, и пары повторялись бы дословно.
    """
    count = len(EFFECTS)
    return EFFECTS[(number + number // count) % count]


def theme_by_number(number):
    """Тема ролика чередуется по его собственному номеру, а не по сквозному."""
    return "white" if number % 2 == 0 else "black"


def audio_args(theme, with_typing):
    music = os.path.join(AUDIO_DIR, "%s.mp3" % theme)
    typing = os.path.join(AUDIO_DIR, "write.mp3")
    for path in [music] + ([typing] if with_typing else []):
        if not os.path.exists(path):
            sys.exit("Не найдена звуковая дорожка: %s" % path)

    if with_typing:
        return ["-i", music, "-i", typing, "-filter_complex",
                "[1:a]volume=1.0[m];[2:a]volume=0.55,atrim=0:4.6,"
                "afade=t=out:st=4.1:d=0.5[k];[m][k]amix=inputs=2:duration=first,"
                "afade=t=out:st=6.4:d=0.6[a]"]
    return ["-i", music, "-filter_complex", "[1:a]afade=t=out:st=6.4:d=0.6[a]"]


def render(text, number, out_path):
    """Собирает ролик с цитатой: эффект и тема выбираются по номеру рилса."""
    if not os.path.exists(FONT_PATH):
        sys.exit("Не найден шрифт: %s" % FONT_PATH)

    name, effect, with_typing = effect_by_number(number)
    theme = theme_by_number(number)
    canvas = Canvas(text, theme)

    work = tempfile.mkdtemp(prefix="reel_")
    try:
        for i in range(int(FPS * DURATION)):
            frame = effect(canvas, i / float(FPS))
            frame.save(os.path.join(work, "f%04d.jpg" % i), "JPEG", quality=94)

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        cmd = [ffmpeg_bin(), "-y", "-loglevel", "error",
               "-framerate", str(FPS), "-i", os.path.join(work, "f%04d.jpg")]
        cmd += audio_args(theme, with_typing)
        cmd += ["-map", "0:v", "-map", "[a]",
                "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
                "-preset", "veryfast", "-crf", "21", "-r", str(FPS),
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
                "-t", str(DURATION), "-movflags", "+faststart", out_path]

        try:
            subprocess.run(cmd, check=True)
        except OSError:
            sys.exit("Не найден ffmpeg (%s), задайте путь в FFMPEG" % ffmpeg_bin())
    finally:
        shutil.rmtree(work, ignore_errors=True)

    return out_path, name, theme


def main():
    if len(sys.argv) < 2:
        print("Использование: python reel.py \"текст цитаты\" [номер] [файл]")
        print("Номер задаёт эффект и тему, счёт с нуля")
        return 1

    text = sys.argv[1]
    number = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(config.OUTPUT, "preview.mp4")

    path, name, theme = render(text, number, out)
    print("Готово: %s (эффект %s, фон %s)"
          % (path, name, "белый" if theme == "white" else "чёрный"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
