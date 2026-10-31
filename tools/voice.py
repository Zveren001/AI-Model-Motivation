# -*- coding: utf-8 -*-
"""Голос ролика через Gemini TTS и время каждого слова для анимации текста.

Сервис не отдаёт таймингов слов, а whisper серверу не по силам: на нём одно ядро
и рядом работает VPN. Поэтому границы фраз берутся из пауз в самой речи,
а внутри фразы слова раскладываются по слогам.
"""

import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave

import config

URL = "https://openrouter.ai/api/v1/audio/speech"
MODEL = "google/gemini-3.8-flash-tts"
STYLE = ("Говори по-русски спокойно, уверенно и неторопливо, как человек, который говорит важную мысль близкому: "
         "тепло, без дикторской подачи и без пафоса. Делай естественные паузы на запятых, тире и точках")
ATTEMPTS = 3
RETRY_DELAY = 20
TIMEOUT = 120
SAMPLE_RATE = 24000
SILENCE_FILTER = "silencedetect=noise=-35dB:d=0.12"
EDGE_TOLERANCE = 0.02

SECONDS_PER_SYLLABLE = 0.25
MIN_LENGTH_RATIO = 0.4
MAX_LENGTH_RATIO = 2.5
VOWELS = "аеёиоуыэюя"

# Стык слов съедает заметную долю времени короткого слова, иначе односложные слова спешат
WORD_GAP = 0.35

PAUSES = {",": 0.28, ";": 0.35, ":": 0.40, "—": 0.42, "–": 0.42,
          ".": 0.60, "!": 0.60, "?": 0.60, "…": 0.70}
PHRASE_END = re.compile(r"(?<=[,;:.!?…])\s+|\s+(?=[—–]\s)|(?<=[—–])\s+")


def ffmpeg_bin():
    return config.get("FFMPEG", "ffmpeg")


def phrases(text):
    """Фразы с концевым знаком: по нему выбирается длина паузы после фразы."""
    parts = [p.strip() for p in PHRASE_END.split(text.strip()) if p.strip()]
    out = []
    for part in parts:
        if part in ("—", "–") and out:
            out[-1] = out[-1] + " " + part
        else:
            out.append(part)
    return out


def spoken_words(text):
    return [w for w in text.split() if re.search(r"\w", w)]


def syllables(word):
    return max(1, sum(1 for ch in word.lower() if ch in VOWELS))


def word_times(text, start, duration):
    """Слова фразы на отрезке от start длиной duration, пропорционально слогам."""
    words = spoken_words(text)
    weights = [syllables(w) + WORD_GAP for w in words]
    total = sum(weights) or 1.0
    out, cursor = [], start
    for word, weight in zip(words, weights):
        span = duration * weight / total
        out.append((cursor, cursor + span, word))
        cursor += span
    return out


def estimated_words(text):
    """Время слов ролика без голоса: по слогам и обычным паузам, без запроса к сервису."""
    words, cursor = [], 0.0
    parts = phrases(text)
    for index, phrase in enumerate(parts):
        length = sum(syllables(w) for w in spoken_words(phrase)) * SECONDS_PER_SYLLABLE
        words += word_times(phrase, cursor, length)
        cursor += length
        if index + 1 < len(parts):
            cursor += PAUSES.get(phrase.rstrip()[-1:], 0.25)
    return words


def request_speech(text, speaker):
    key = config.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("не задан OPENROUTER_API_KEY")
    body = json.dumps({"model": MODEL, "voice": speaker, "input": text,
                       "response_format": "pcm", "instructions": STYLE}).encode("utf-8")
    req = urllib.request.Request(URL, data=body, headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        if not resp.headers.get("Content-Type", "").startswith("audio"):
            raise RuntimeError("сервис вернул не звук: %s" % resp.read(200).decode("utf-8", "replace"))
        return resp.read()


def check_length(pcm, text):
    """Звук сильно короче или длиннее текста — модель оборвала фразу или прочитала лишнее."""
    expected = estimated_words(text)[-1][1]
    seconds = len(pcm) / 2.0 / SAMPLE_RATE
    if not MIN_LENGTH_RATIO * expected <= seconds <= MAX_LENGTH_RATIO * expected:
        raise RuntimeError("длина звука %.1f с при ожидаемых %.1f с" % (seconds, expected))


def silences(pcm):
    done = subprocess.run(
        [ffmpeg_bin(), "-hide_banner", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "pipe:0",
         "-af", SILENCE_FILTER, "-f", "null", "-"], input=pcm, capture_output=True, check=True)
    log = done.stderr.decode("utf-8", "replace")
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    return list(zip(starts, ends))


def speech_words(pcm, text):
    """Границы фраз — самые длинные паузы речи; мелкие паузы бывают и внутри фразы."""
    parts = phrases(text)
    total = len(pcm) / 2.0 / SAMPLE_RATE
    gaps = silences(pcm)
    start = gaps[0][1] if gaps and gaps[0][0] <= EDGE_TOLERANCE else 0.0
    end = gaps[-1][0] if gaps and gaps[-1][1] >= total - EDGE_TOLERANCE else total
    inner = [g for g in gaps if g[0] > start and g[1] < end]
    needed = len(parts) - 1
    if len(inner) < needed:
        return word_times(text, start, end - start)
    longest = sorted(inner, key=lambda g: g[1] - g[0], reverse=True)[:needed]
    boundaries = sorted(longest)
    words, cursor = [], start
    for phrase, gap in zip(parts, boundaries + [(end, end)]):
        words += word_times(phrase, cursor, gap[0] - cursor)
        cursor = gap[1]
    return words


def write_wav(path, pcm):
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(pcm)


def error_text(e):
    return e.read().decode("utf-8", "replace")[:200] if isinstance(e, urllib.error.HTTPError) else str(e)


def synthesize(text, out_path, speaker, log=print):
    """Пишет WAV и возвращает [(начало, конец, слово)]; None — голоса нет, ролик выйдет тихим."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            pcm = request_speech(text, speaker)
            check_length(pcm, text)
            words = speech_words(pcm, text)
            write_wav(out_path, pcm)
            return words
        except Exception as e:  # noqa: BLE001
            log("Голос %s, попытка %d из %d: %s" % (speaker, attempt, ATTEMPTS, error_text(e)))
            if attempt < ATTEMPTS and config.get("OPENROUTER_API_KEY"):
                time.sleep(RETRY_DELAY * attempt)
    return None


def main():
    if len(sys.argv) < 4:
        print("Использование: python voice.py \"текст\" файл.wav Leda")
        return 1
    words = synthesize(sys.argv[1], sys.argv[2], sys.argv[3])
    if not words:
        return 1
    print("фразы:", " | ".join(phrases(sys.argv[1])))
    for start, end, word in words:
        print("%6.2f  %6.2f  %s" % (start, end, word))
    return 0


if __name__ == "__main__":
    sys.exit(main())
