# -*- coding: utf-8 -*-
"""Сборка вертикального ролика: видеоряд, голос и слова на экране в ритм речи.

Речь складывается из крючка, объяснения, совета и вопроса. Светлана
озвучивает её и отдаёт тайминги слов, по ним субтитры выводятся группами
по два-три слова. Фон — вертикальный клип из стока, затемнённый, чтобы
текст читался; под голосом тихо идёт музыкальная подложка.

Первая группа слов стоит с нулевого кадра: у ролика нет пустого начала,
а у YouTube — пустой обложки.
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
LEAD = 0.35
TAIL = 0.9
MUSIC_VOLUME = 0.12
CTA_LINE = "Напиши в комментариях."

AUDIO_DIR = os.path.join(config.ROOT, "assets", "audio")
FONTS_DIR = os.path.join(config.ROOT, "assets", "fonts")
CAPTION_FONT = "Roboto-Bold.ttf"
MUSIC = ["white.mp3", "black.mp3"]

VIDEO_CHAIN = ("scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1,"
               "fps=%d,eq=brightness=-0.12:contrast=1.02:saturation=0.85" % (W, H, W, H, FPS))


def ffmpeg_bin():
    return config.get("FFMPEG", "ffmpeg")


def script_for(quote, cta=False):
    parts = [quote["hook"], quote["reasoning"], quote["action"], quote["question"]]
    if cta:
        parts.append(CTA_LINE)
    return " ".join(p.strip() for p in parts if p and p.strip())


def render(quote, number, out_path, cta=False, clip=None, log=print):
    """Собирает ролик из цитаты с развёрткой.

    Возвращает путь, имя клипа, длительность и число слов. Клип можно передать
    явно — для проб; иначе берётся из стока по теме цитаты. Без голоса или
    без клипа ролик не собирается: лучше пропущенный слот, чем немой слайд.
    """
    script = script_for(quote, cta)
    work = tempfile.mkdtemp(prefix="reel_")
    try:
        voice_path = os.path.join(work, "voice.mp3")
        words = voice.speak(script, voice_path)
        speech_end = words[-1][1]
        duration = round(LEAD + speech_end + TAIL, 2)

        shifted = [(s + LEAD, e + LEAD, w) for s, e, w in captions.attach_punctuation(words, script)]
        ass_path = os.path.join(work, "captions.ass")
        groups = captions.write(shifted, duration, ass_path)
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
            "[2:a]atrim=0:%.2f,volume=%.2f,afade=t=out:st=%.2f:d=0.8[bed];"
            "[vo][bed]amix=inputs=2:duration=first:normalize=0[a]"
            % (VIDEO_CHAIN, os.path.basename(ass_path), ".",
               delay, delay, duration, duration, MUSIC_VOLUME, duration - 0.8)
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
               "-preset", "veryfast", "-crf", "22", "-r", str(FPS),
               "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
               "-movflags", "+faststart", out_path]
        try:
            subprocess.run(cmd, check=True, cwd=work)
        except OSError:
            sys.exit("Не найден ffmpeg (%s), задайте путь в FFMPEG" % ffmpeg_bin())

        log("Речь %.1f с, слов %d, групп на экране %d" % (speech_end, len(words), len(groups)))
        return out_path, os.path.basename(clip), duration, len(words)
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
        print("Использование: python reel.py --id=N [файл] [--cta] [--clip=путь]")
        print("Цитата берётся из базы вместе с крючком, объяснением, советом и вопросом")
        return 1

    quote, clip, out = None, None, os.path.join(config.OUTPUT, "preview.mp4")
    for a in sys.argv[1:]:
        if a.startswith("--id="):
            quote = quote_by_id(int(a.split("=", 1)[1]))
        elif a.startswith("--clip="):
            clip = a.split("=", 1)[1]
        elif not a.startswith("--"):
            out = a
    if not quote:
        print("Нужен ключ --id=N")
        return 1
    if not all(quote.get(k) for k in ("hook", "reasoning", "action", "question")):
        print("У цитаты #%d нет развёртки" % quote["id"])
        return 1

    path, clip_name, duration, words = render(quote, quote["id"], out,
                                              cta="--cta" in sys.argv, clip=clip)
    print("Готово: %s (%.1f с, клип %s, слов %d)" % (path, duration, clip_name, words))
    return 0


if __name__ == "__main__":
    sys.exit(main())
