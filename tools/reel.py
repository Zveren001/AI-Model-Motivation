# -*- coding: utf-8 -*-
"""Сборка вертикального ролика: цитата голосом поверх фона.

Светлана читает цитату и короткий призыв, слова цитаты загораются в ритм
речи. Ролик замкнут в петлю: последний кадр совпадает с первым, потому что
цитата к концу возвращается в приглушённый вид.

Фон бывает четырёх видов, и это предмет сравнения: однотонный, клип из
стока, процедурный градиент и однотонный без голоса. Озвучка вызывается
всегда, даже для немого формата: из неё берутся тайминги слов, поэтому
ритм и длительность у всех четырёх совпадают и различается ровно один слой.

Клип из стока каждый раз уникализируется — зеркало, оттенок, скорость
и медленный проезд кадром. Без этого YouTube иногда засчитывает ролик
повторно используемым контентом и не даёт раздачу вовсе.
"""

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile

import captions
import config
import footage
import voice

W, H = 1080, 1920
FPS = 30
LEAD = 0.3
GAP = 0.35
TAIL = 0.75
MUSIC_VOLUME = 0.14
SILENT_MUSIC_VOLUME = 0.32

STYLES = ("fon", "stock", "gradient", "nemoy")
PLAIN_BG = {"white": "0xF2F2F2", "black": "0x111111"}
GRADIENT_COLOURS = [
    ("0x0B1220", "0x24405E"), ("0x1B1020", "0x4A2A55"), ("0x101A14", "0x2C4A38"),
    ("0x1A1410", "0x5A3A22"), ("0x0E1418", "0x2E4A52"), ("0x160E16", "0x4A2440"),
]

CTA_LINES = {
    "comment": ("Согласен? Напиши в комментариях.", "Напиши в комментариях"),
    "subscribe": ("Подпишись, одна мысль каждый день.", "Подпишись"),
    "like": ("Поставь лайк, если это про тебя.", "Лайк, если про тебя"),
}

AUDIO_DIR = os.path.join(config.ROOT, "assets", "audio")
FONTS_DIR = os.path.join(config.ROOT, "assets", "fonts")
CAPTION_FONT = "Roboto-Bold.ttf"
MUSIC = ["white.mp3", "black.mp3"]


def ffmpeg_bin():
    return config.get("FFMPEG", "ffmpeg")


def style_by_number(number):
    return STYLES[number % len(STYLES)]


def theme_by_number(number):
    return "white" if number // len(STYLES) % 2 == 0 else "black"


def script_for(text, cta):
    spoken = CTA_LINES.get(cta, (None, None))[0]
    if not spoken:
        return text
    return "%s %s" % (text.rstrip(".") + ".", spoken)


def stock_chain(rnd):
    """Клип из стока с уникализацией: зеркало, оттенок, скорость, проезд кадром."""
    zoom = rnd.uniform(1.10, 1.18)
    scaled_w, scaled_h = int(W * zoom), int(H * zoom)
    drift_x = rnd.uniform(-1, 1) * (scaled_w - W) / 2.2
    drift_y = rnd.uniform(-1, 1) * (scaled_h - H) / 2.2
    chain = "hflip," if rnd.random() < 0.5 else ""
    chain += "setpts=%.3f*PTS," % rnd.uniform(0.96, 1.04)
    chain += ("scale=%d:%d:force_original_aspect_ratio=increase,"
              % (scaled_w, scaled_h))
    chain += ("crop=%d:%d:x='(iw-ow)/2+%.1f*sin(t/6)':y='(ih-oh)/2+%.1f*sin(t/8)',"
              % (W, H, drift_x, drift_y))
    chain += "setsar=1,fps=%d,hue=h=%d," % (FPS, rnd.randint(-10, 10))
    chain += "eq=brightness=-0.22:contrast=1.05:saturation=0.75,vignette=angle=PI/3.6"
    return chain


def background(style, theme, number, rnd, log):
    """Источник фона для ffmpeg: аргументы входа, цепочка фильтров и имя источника."""
    if style == "stock":
        clip = footage.pick_clip(number, log=log)
        if not clip:
            raise RuntimeError("нет видеоряда: сток недоступен и кэш пуст")
        return (["-stream_loop", "-1", "-i", os.path.abspath(clip)],
                stock_chain(rnd), os.path.basename(clip))

    if style == "gradient":
        first, second = GRADIENT_COLOURS[number % len(GRADIENT_COLOURS)]
        source = ("gradients=s=%dx%d:c0=%s:c1=%s:speed=%.4f:r=%d"
                  % (W, H, first, second, rnd.uniform(0.002, 0.006), FPS))
        return (["-f", "lavfi", "-i", source],
                "noise=alls=7:allf=t,vignette=angle=PI/4", "градиент")

    source = "color=c=%s:s=%dx%d:r=%d" % (PLAIN_BG[theme], W, H, FPS)
    return ["-f", "lavfi", "-i", source], "null", "фон %s" % theme


def audio_chain(style, duration, delay):
    """Голос с музыкальной подложкой; в немом формате музыка идёт одна и громче."""
    if style == "nemoy":
        return ("[2:a]atrim=0:%.2f,volume=%.2f,afade=t=in:st=0:d=0.5,"
                "afade=t=out:st=%.2f:d=0.6[a]"
                % (duration, SILENT_MUSIC_VOLUME, duration - 0.6))
    return ("[1:a]adelay=%d|%d,apad=whole_dur=%.2f[vo];"
            "[2:a]atrim=0:%.2f,volume=%.2f,afade=t=out:st=%.2f:d=0.6[bed];"
            "[vo][bed]amix=inputs=2:duration=first:normalize=0[a]"
            % (delay, delay, duration, duration, MUSIC_VOLUME, duration - 0.6))


def render(quote, number, out_path, style=None, cta=None, effect=None,
           theme=None, log=print):
    """Собирает ролик из цитаты.

    Возвращает путь, описание фона, длительность и словарь с фактическими
    формате, эффектом и темой — их записывает в журнал вызывающий.
    """
    style = style if style in STYLES else style_by_number(number)
    effect = effect if effect in captions.EFFECTS else captions.EFFECT_ORDER[number % 5]
    theme = theme or theme_by_number(number)
    rnd = random.Random("%s-%s-%s" % (quote["id"], number, style))

    text = quote["text"]
    script = script_for(text, cta)
    shown = CTA_LINES.get(cta, (None, None))[1]

    work = tempfile.mkdtemp(prefix="reel_")
    try:
        voice_path = os.path.join(work, "voice.mp3")
        words = voice.speak(script, voice_path)
        quote_words = [(s + LEAD, e + LEAD, w) for s, e, w in words[:len(text.split())]]
        cta_words = [(s + LEAD, e + LEAD, w) for s, e, w in words[len(text.split()):]]
        if not quote_words:
            raise RuntimeError("озвучка вернула меньше слов, чем в цитате")

        if cta_words and shown:
            cta_slot = (cta_words[0][0] - GAP / 2, cta_words[-1][1] + GAP, shown)
            speech_end = cta_words[-1][1]
        else:
            cta_slot, speech_end = None, quote_words[-1][1]
        duration = round(speech_end + TAIL, 2)

        colors = captions.DARK_ON_LIGHT if (style in ("fon", "nemoy") and theme == "white") \
            else captions.LIGHT_ON_DARK
        ass_path = os.path.join(work, "captions.ass")
        size, rows = captions.write(quote_words, cta_slot, duration, ass_path,
                                    effect, colors)
        shutil.copy(os.path.join(FONTS_DIR, CAPTION_FONT), work)

        source_args, video_chain, source_name = background(style, theme, number, rnd, log)
        music = os.path.join(AUDIO_DIR, MUSIC[number % len(MUSIC)])
        # ffmpeg запускается из рабочей папки, а субтитры и шрифт идут по коротким
        # именам: абсолютный путь с двоеточием и пробелами в опции фильтра
        # требует двухуровневого экранирования и на Windows ломается
        filters = ("[0:v]%s,subtitles=%s:fontsdir=.[v];%s"
                   % (video_chain, os.path.basename(ass_path),
                      audio_chain(style, duration, int(LEAD * 1000))))

        out_path = os.path.abspath(out_path)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        cmd = [ffmpeg_bin(), "-y", "-loglevel", "error"]
        cmd += source_args
        cmd += ["-i", voice_path, "-stream_loop", "-1", "-i", music,
                "-filter_complex", filters,
                "-map", "[v]", "-map", "[a]", "-t", "%.2f" % duration,
                "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
                "-preset", "veryfast", "-crf", "23", "-maxrate", "6M", "-bufsize", "12M",
                "-r", str(FPS),
                "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
                "-movflags", "+faststart", out_path]
        try:
            subprocess.run(cmd, check=True, cwd=work)
        except OSError:
            sys.exit("Не найден ffmpeg (%s), задайте путь в FFMPEG" % ffmpeg_bin())

        log("Речь %.1f с, слов в цитате %d, кегль %d, строк %d"
            % (speech_end, len(quote_words), size, rows))
        return out_path, source_name, duration, {"style": style, "effect": effect,
                                                 "theme": theme}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def quote_by_id(quote_id):
    with open(config.QUOTES, encoding="utf-8") as f:
        for q in json.load(f)["quotes"]:
            if q["id"] == quote_id:
                return q
    sys.exit("Цитата #%d не найдена" % quote_id)


def main():
    if len(sys.argv) < 2:
        print("Использование: python reel.py --id=N [файл] [--style=%s]"
              % "|".join(STYLES))
        print("   [--cta=comment|subscribe|like] [--effect=%s] [--theme=white|black]"
              % "|".join(captions.EFFECT_ORDER))
        return 1

    quote, out = None, os.path.join(config.OUTPUT, "preview.mp4")
    opts = {}
    for a in sys.argv[1:]:
        if a.startswith("--id="):
            quote = quote_by_id(int(a.split("=", 1)[1]))
        elif a.startswith("--"):
            key, _, value = a[2:].partition("=")
            if key in ("style", "cta", "effect", "theme"):
                opts[key] = value
        else:
            out = a
    if not quote:
        print("Нужен ключ --id=N")
        return 1

    path, source, duration, meta = render(quote, quote["id"], out, **opts)
    print("Готово: %s (%.1f с, %s, формат %s, эффект %s, призыв %s)"
          % (path, duration, source, meta["style"], meta["effect"],
             opts.get("cta") or "нет"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
