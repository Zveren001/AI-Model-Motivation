# -*- coding: utf-8 -*-
"""Сборка ролика: сток, текстовый слой из typefx, голос, подложка и стук клавиш.

Кадры текста рисует Pillow и отдаёт в ffmpeg сырым потоком через stdin —
сотни PNG на диск писать не нужно. Тень под текстом ffmpeg строит сам из
прозрачности слоя: размытая чёрная копия держит читаемость на любом клипе.
"""

import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

import config
import typefx
import voice

W, H, FPS = typefx.W, typefx.H, 30
LEAD = 0.2
HOLD = 2.0
MIN_DURATION = 6.0

AUDIO_DIR = os.path.join(config.ROOT, "assets", "audio")
MUSIC = ("white.mp3", "black.mp3")
CLICKS = os.path.join(AUDIO_DIR, "write.mp3")

VIGNETTE = "vignette=angle=PI/4"
GRADES = {
    "dark": "eq=brightness={b:.3f}:contrast=1.05:saturation=0.8," + VIGNETTE,
    "blur": "gblur=sigma=18,eq=brightness={b:.3f}:saturation=0.85," + VIGNETTE,
    "bw": "hue=s=0,eq=brightness={b:.3f}:contrast=1.12," + VIGNETTE,
    "warm": ("colorbalance=rs=0.10:gs=0.02:bs=-0.10:rm=0.06:bm=-0.06,"
             "eq=brightness={b:.3f}:saturation=0.9," + VIGNETTE),
    "zoom": "eq=brightness={b:.3f}:contrast=1.05:saturation=0.8," + VIGNETTE,
}
# Яркость центра кадра, где стоит текст, после обработки. Одинаковое
# затемнение для всех клипов делает тёмные сцены чёрными, а светлые
# оставляет слишком светлыми, поэтому сдвиг считается по самому клипу.
TARGET_LUMA = 0.25
LOUDNESS = "loudnorm=I=-14:TP=-1.5:LRA=11"
GRADE_NAMES = {"dark": "затемнение", "blur": "размытие", "bw": "чёрно-белый",
               "warm": "тёплый", "zoom": "наезд камеры"}

VOICES = {
    "нет": None,
    "обычный": {"rate": "+0%", "pitch": "+0Hz", "pause_scale": 1.0, "final_pause": 0.0},
    "медленный": {"rate": "-10%", "pitch": "+0Hz", "pause_scale": 1.5, "final_pause": 0.0},
    "бодрый": {"rate": "+6%", "pitch": "+0Hz", "pause_scale": 0.8, "final_pause": 0.0},
    "с акцентом": {"rate": "-4%", "pitch": "+0Hz", "pause_scale": 1.15, "final_pause": 0.45},
    "низкий": {"rate": "-6%", "pitch": "-8Hz", "pause_scale": 1.2, "final_pause": 0.2},
}

TEXT_STYLES = {
    "тень": {"sizes": range(104, 47, -2), "center": 0.5},
    "крупно": {"sizes": range(124, 55, -2), "center": 0.44},
}


def ffmpeg_bin():
    return config.get("FFMPEG", "ffmpeg")


def tokens_of(text):
    """Слова цитаты для экрана; тире держится за предыдущим словом и не начинает строку."""
    out = []
    for token in text.split():
        if token in ("—", "–") and out:
            out[-1] = out[-1] + " " + token
        else:
            out.append(token)
    return out


def core(word):
    return re.sub(r"[^\w-]", "", word).lower().replace("ё", "е")


def align(tokens, words):
    """Время каждого слова на экране по таймингам голоса — по тексту, а не по счёту.

    Считать по порядку нельзя: тире и кавычки голос не произносит, и счёт
    сбивается на слово — так в ролик однажды приклеилось «подпишись».
    """
    starts, ends, j, last = [], [], 0, 0.0
    for token in tokens:
        c = core(token)
        match = next((k for k in range(j, min(j + 3, len(words)))
                      if core(words[k][2]) == c), None) if c else None
        if match is None and c and j < len(words):
            match = j
        if match is None:
            starts.append(last)
            ends.append(last)
            continue
        starts.append(words[match][0])
        ends.append(words[match][1])
        last, j = words[match][1], match + 1
    return starts, ends


def centre_luma(clip):
    """Средняя яркость средней трети кадра по двум моментам клипа, от 0 до 1."""
    values = []
    for at in ("1", "4"):
        raw = subprocess.run(
            [ffmpeg_bin(), "-loglevel", "error", "-ss", at, "-i", clip, "-frames:v", "1",
             "-vf", "scale=108:192", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
            stdout=subprocess.PIPE).stdout
        if len(raw) == 108 * 192:
            values.append(sum(raw[108 * 64:108 * 128]) / (108 * 64 * 255.0))
    return sum(values) / len(values) if values else 0.45


def motion_chain(rnd, zoom, colour_shift):
    """Уникализация клипа: зеркало, скорость, оттенок и движение кадра."""
    chain = "hflip," if rnd.random() < 0.5 else ""
    chain += "setpts=%.3f*PTS," % rnd.uniform(0.96, 1.04)
    if zoom:
        chain += ("scale=1296:2304:force_original_aspect_ratio=increase,crop=1296:2304,"
                  "zoompan=z='min(1+0.0011*on,1.2)':x='iw/2-(iw/zoom/2)'"
                  ":y='ih/2-(ih/zoom/2)':d=1:s=%dx%d:fps=%d," % (W, H, FPS))
    else:
        scale = rnd.uniform(1.10, 1.18)
        sw, sh = int(W * scale), int(H * scale)
        dx = rnd.uniform(-1, 1) * (sw - W) / 2.2
        dy = rnd.uniform(-1, 1) * (sh - H) / 2.2
        chain += ("scale=%d:%d:force_original_aspect_ratio=increase,"
                  "crop=%d:%d:x='(iw-ow)/2+%.1f*sin(t/6)':y='(ih-oh)/2+%.1f*sin(t/8)',"
                  "fps=%d," % (sw, sh, W, H, dx, dy, FPS))
    chain += "setsar=1"
    if colour_shift:
        chain += ",hue=h=%d" % rnd.randint(-8, 8)
    return chain


def render(text, out_path, clip, effect, grade="dark", text_style="тень",
           voice_preset="обычный", seed=0, log=print):
    """Собирает готовый ролик и возвращает его длительность в секундах."""
    rnd = random.Random(seed)
    style = TEXT_STYLES[text_style]
    preset = VOICES[voice_preset]
    tokens = tokens_of(text)

    work = tempfile.mkdtemp(prefix="clip_")
    try:
        voice_path = os.path.join(work, "voice.wav")
        words = voice.speak_phrases(text, voice_path, **(preset or VOICES["обычный"]))
        starts, ends = align(tokens, words)
        timeline = typefx.Timeline([s + LEAD for s in starts], [e + LEAD for e in ends])
        layout = typefx.Layout(tokens, style["sizes"], style["center"])
        duration = round(max(MIN_DURATION, timeline.speech_end + HOLD), 2)

        inputs = ["-stream_loop", "-1", "-i", os.path.abspath(clip),
                  "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "%dx%d" % (W, H),
                  "-r", str(FPS), "-i", "pipe:0"]
        brightness = max(-0.42, min(0.08, TARGET_LUMA - centre_luma(clip)))
        video = "[0:v]%s,%s[bg];" % (motion_chain(rnd, grade == "zoom", grade != "bw"),
                                     GRADES[grade].format(b=brightness))
        video += ("[1:v]format=rgba,split[txt][sh];"
                  "[sh]colorchannelmixer=rr=0:gg=0:bb=0:aa=0.9,gblur=sigma=10[shadow];"
                  "[bg][shadow]overlay=format=auto[base];"
                  "[base][txt]overlay=format=auto,format=yuv420p[v]")

        audio, mix, n = [], [], 2
        music = os.path.join(AUDIO_DIR, MUSIC[rnd.randrange(len(MUSIC))])
        inputs += ["-stream_loop", "-1", "-i", music]
        audio.append("[%d:a]atrim=0:%.2f,volume=%.2f,afade=t=in:d=0.4,afade=t=out:st=%.2f:d=0.7[m]"
                     % (n, duration, 0.18 if preset else 1.0, duration - 0.7))
        mix.append("[m]")
        n += 1
        if preset:
            inputs += ["-i", voice_path]
            ms = int(LEAD * 1000)
            audio.append("[%d:a]adelay=%d|%d,apad[vo]" % (n, ms, ms))
            mix.append("[vo]")
            n += 1
        if effect in typefx.CLICK_EFFECTS:
            typing = max(0.6, timeline.speech_end - timeline.starts[0])
            ms = int(timeline.starts[0] * 1000)
            inputs += ["-stream_loop", "-1", "-i", CLICKS]
            audio.append("[%d:a]atrim=0:%.2f,volume=%.2f,afade=t=out:st=%.2f:d=0.4,"
                         "adelay=%d|%d[k]" % (n, typing, 0.35 if preset else 0.55,
                                              max(0.0, typing - 0.4), ms, ms))
            mix.append("[k]")
            n += 1
        audio.append("%samix=inputs=%d:duration=first:normalize=0,%s[a]"
                     % ("".join(mix), len(mix), LOUDNESS))

        out_path = os.path.abspath(out_path)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        cmd = [ffmpeg_bin(), "-y", "-loglevel", "error"] + inputs + [
            "-filter_complex", video + ";" + ";".join(audio),
            "-map", "[v]", "-map", "[a]", "-t", "%.2f" % duration,
            "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-preset", "veryfast", "-crf", "21", "-maxrate", "8M", "-bufsize", "16M",
            "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
            "-movflags", "+faststart", out_path]

        errors_path = os.path.join(work, "ffmpeg.txt")
        with open(errors_path, "wb") as errors:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=errors)
            try:
                for i in range(int(duration * FPS) + 1):
                    frame = typefx.frame_at(effect, layout, timeline, i / float(FPS))
                    proc.stdin.write(frame.tobytes())
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            code = proc.wait()
        if code != 0:
            with open(errors_path, encoding="utf-8", errors="replace") as f:
                raise RuntimeError("ffmpeg: %s" % f.read()[-800:])
        return duration
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    if len(sys.argv) < 4:
        print("Использование: python compose.py \"цитата\" клип.mp4 выход.mp4 [эффект] [фон] [текст] [голос]")
        return 1
    args = sys.argv[1:] + [None] * 7
    text, clip, out = args[0], args[1], args[2]
    duration = render(text, out, clip, args[3] or "pechat_posimvolno", args[4] or "dark",
                      args[5] or "тень", args[6] or "обычный")
    print("Готово: %s, %.1f с" % (out, duration))
    return 0


if __name__ == "__main__":
    sys.exit(main())
