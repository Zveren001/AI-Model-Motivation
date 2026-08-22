# -*- coding: utf-8 -*-
"""Отрисовка цитаты на однотонном фоне.

Картинка собирается программно, без нейросетей: фон, текст по центру,
автоподбор кегля под длину цитаты. Занимает доли секунды.
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

import config

SIZE = 1080
MARGIN = 130
FONT_NAME = config.get("FONT", "Constantine.ttf")
FONT_PATH = os.path.join(config.ROOT, "assets", "fonts", FONT_NAME)

WHITE_BG = ((255, 255, 255), (17, 17, 17))
BLACK_BG = ((17, 17, 17), (255, 255, 255))


def theme_for_hour(hour):
    """Слоты чередуются: 00 белый, 06 чёрный, 12 белый, 18 чёрный."""
    return WHITE_BG if (hour // 6) % 2 == 0 else BLACK_BG


def wrap(text, font, draw, max_width):
    """Переносит по словам, не разрывая их."""
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


def fit_text(draw, text, max_width, max_height):
    """Подбирает самый крупный кегль, при котором текст влезает в блок."""
    for size in range(96, 33, -2):
        font = ImageFont.truetype(FONT_PATH, size)
        lines = wrap(text, font, draw, max_width)
        line_height = int(size * 1.28)
        if line_height * len(lines) <= max_height and len(lines) <= 7:
            return font, lines, line_height
    font = ImageFont.truetype(FONT_PATH, 34)
    return font, wrap(text, font, draw, max_width), 44


def render(text, hour, out_path):
    """Рисует картинку и сохраняет в JPEG."""
    if not os.path.exists(FONT_PATH):
        sys.exit("Не найден шрифт: %s" % FONT_PATH)

    bg, fg = theme_for_hour(hour)
    image = Image.new("RGB", (SIZE, SIZE), bg)
    draw = ImageDraw.Draw(image)

    box = SIZE - MARGIN * 2
    font, lines, line_height = fit_text(draw, text, box, box)

    total = line_height * len(lines)
    y = (SIZE - total) // 2

    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((SIZE - w) / 2, y), line, font=font, fill=fg)
        y += line_height

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    image.save(out_path, "JPEG", quality=92, optimize=True)
    return out_path


def main():
    if len(sys.argv) < 2:
        print("Использование: python render.py \"текст цитаты\" [час] [файл]")
        print("Час определяет тему: 0 и 12 — белый фон, 6 и 18 — чёрный")
        return 1

    text = sys.argv[1]
    hour = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(config.ROOT, "output", "preview.jpg")

    path = render(text, hour, out)
    bg = "белый" if theme_for_hour(hour) is WHITE_BG else "чёрный"
    print("Готово: %s (%s фон)" % (path, bg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
