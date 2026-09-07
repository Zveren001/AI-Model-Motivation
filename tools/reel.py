# -*- coding: utf-8 -*-
"""Сборка вертикального ролика: цитата голосом поверх видеоряда.

Светлана читает цитату и короткий призыв, слова цитаты загораются в ритм
речи поверх затемнённого клипа из стока. Ролик замкнут в петлю: последний
кадр совпадает с первым, потому что цитата к концу возвращается
в приглушённый вид.

Без голоса или без клипа ролик не собирается: лучше пропущенный слот,
чем немой слайд.
"""

import json
import os
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

CTA_LINES = {
    "comment": ("Согласен? Напиши в комментариях.", "Напиши в комментариях"),
    "subscribe": ("Подпишись, одна мысль каждый день.", "Подпишись"),
    "like": ("Поставь лайк, если это про тебя.", "Лайк, если про тебя"),
}

AUDIO_DIR = os.path.join(config.ROOT, "assets", "audio")
FONTS_DIR = os.path.join(config.ROOT, "assets", "fonts")
CAPTION_FONT = "Roboto-Bold.ttf"
MUSIC = ["white.mp3", "black.mp3"]

VIDEO_CHAIN = ("scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1,"
               "fps=%d,eq=brightness=-0.22:contrast=1.05:saturation=0.75,vignette=angle=PI/3.6" % (W, H, W, H, FPS))


def ffmpeg_bin():
    return config.get("FFMPEG", "ffmpeg")


def split_words(words, spoken):
    """Делит тайминги на слова цитаты и слова призыва по числу произнесённых."""
    return words[:spoken], words[spoken:]


def effect_by_number(number):
    order = captions.EFFECT_ORDER
    return order[number % len(order)]


def render(quote, number, out_path, cta=None, effect=None, clip=None, log=print):
    """Собирает ролик из цитаты.

    Возвращает путь, имя клипа, длительность и имя эффекта. Эффект задаёт,
    как слово выглядит в момент, когда его произносят.
    """
    text = quote["text"]
    spoken, shown = CTA_LINES.get(cta, (None, None))
    script = text if not spoken else "%s %s" % (text.rstrip(".") + ".", spoken)

    work = tempfile.mkdtemp(prefix="reel_")
    try:
        voice_path = os.path.join(work, "voice.mp3")
        words = voice.speak(script, voice_path)
        quote_words, cta_words = split_words(words, len(text.split()))
        if not quote_words:
            raise RuntimeError("озвучка вернула меньше слов, чем в цитате")

        shift = LEAD
        quote_words = [(s + shift, e + shift, w) for s, e, w in quote_words]
        cta_words = [(s + shift, e + shift, w) for s, e, w in cta_words]

        if cta_words:
            cta_slot = (cta_words[0][0] - GAP / 2, cta_words[-1][1] + GAP, shown)
            speech_end = cta_words[-1][1]
        else:
            cta_slot, speech_end = None, quote_words[-1][1]
        duration = round(speech_end + TAIL, 2)

        effect = effect if effect in captions.EFFECTS else effect_by_number(number)
        ass_path = os.path.join(work, "captions.ass")
        size, rows = captions.write(quote_words, cta_slot, duration, ass_path, effect)
        shutil.copy(os.path.join(FONTS_DIR, CAPTION_FONT), work)

        clip = clip or footage.pick(quote["topic"], log=log)
        if not clip:
            raise RuntimeError("нет видеоряда: сток недоступен и кэш пуст")

        music = os.path.join(AUDIO_DIR, MUSIC[number % len(MUSIC)])
        delay = int(LEAD * 1000)
        # ffmpeg запускается из рабочей папки, а субтитры и шрифт идут по коротким
        # именам: абсолютный путь с двоеточием и пробелами в опции фильтра
        # требует двухуровневого экранирования и на Windows ломается
        filters = (
            "[0:v]%s,subtitles=%s:fontsdir=%s[v];"
            "[1:a]adelay=%d|%d,apad=whole_dur=%.2f[vo];"
            "[2:a]atrim=0:%.2f,volume=%.2f,afade=t=out:st=%.2f:d=0.6[bed];"
            "[vo][bed]amix=inputs=2:duration=first:normalize=0[a]"
            % (VIDEO_CHAIN, os.path.basename(ass_path), ".",
               delay, delay, duration, duration, MUSIC_VOLUME, duration - 0.6)
        )
        out_path = os.path.abspath(out_path)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        cmd = [ffmpeg_bin(), "-y", "-loglevel", "error",
               "-stream_loop", "-1", "-i", os.path.abspath(clip),
               "-i", voice_path,
               "-stream_loop", "-1", "-i", music,
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

        log("Речь %.1f с, слов в цитате %d, кегль %d, строк %d, эффект %s"
            % (speech_end, len(quote_words), size, rows, effect))
        return out_path, os.path.basename(clip), duration, effect
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
        print("Использование: python reel.py --id=N [файл] [--cta=comment|subscribe|like]"
              " [--effect=%s] [--clip=путь]" % "|".join(captions.EFFECT_ORDER))
        return 1

    quote, clip, cta, effect = None, None, None, None
    out = os.path.join(config.OUTPUT, "preview.mp4")
    for a in sys.argv[1:]:
        if a.startswith("--id="):
            quote = quote_by_id(int(a.split("=", 1)[1]))
        elif a.startswith("--clip="):
            clip = a.split("=", 1)[1]
        elif a.startswith("--cta="):
            cta = a.split("=", 1)[1]
        elif a.startswith("--effect="):
            effect = a.split("=", 1)[1]
        elif not a.startswith("--"):
            out = a
    if not quote:
        print("Нужен ключ --id=N")
        return 1

    path, clip_name, duration, effect = render(quote, quote["id"], out, cta=cta,
                                               effect=effect, clip=clip)
    print("Готово: %s (%.1f с, клип %s, призыв %s, эффект %s)"
          % (path, duration, clip_name, cta or "нет", effect))
    return 0


if __name__ == "__main__":
    sys.exit(main())
