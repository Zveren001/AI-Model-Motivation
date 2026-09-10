# -*- coding: utf-8 -*-
"""Озвучка текста голосом Светланы через edge-tts с таймингами слов.

Microsoft запрещает в edge-tts собственную SSML-разметку, поэтому тег паузы
не работает, а сплошной синтез проглатывает запятые и тире. Текст режется
на фразы по знакам препинания, каждая озвучивается отдельно и склеивается
с тишиной нужной длины — так паузу задаём мы, а не сервис.
"""

import asyncio
import re
import subprocess
import sys
import time
import wave

import edge_tts

import config

VOICE = config.get("VOICE", "ru-RU-SvetlanaNeural")
RATE = config.get("VOICE_RATE", "+0%")
PITCH = config.get("VOICE_PITCH", "+0Hz")
ATTEMPTS = 3
RETRY_DELAY = 20
SAMPLE_RATE = 24000
TAIL_KEEP = 0.06

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


def tts_text(phrase):
    """Тире в конце фразы сервис не озвучивает интонацией, запятая — да."""
    return re.sub(r"\s*[—–]$", ",", phrase)


async def _speak(text, rate, pitch):
    communicate = edge_tts.Communicate(text, VOICE, rate=rate, pitch=pitch,
                                       boundary="WordBoundary")
    words, audio = [], bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            start = chunk["offset"] / 1e7
            words.append((start, start + chunk["duration"] / 1e7, chunk["text"]))
    if not audio or not words:
        raise RuntimeError("сервис вернул пустой ответ")
    return bytes(audio), words


def _speak_retry(text, rate, pitch):
    last = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return asyncio.run(_speak(text, rate, pitch))
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < ATTEMPTS:
                time.sleep(RETRY_DELAY * attempt)
    raise RuntimeError("озвучка не удалась после %d попыток: %s" % (ATTEMPTS, last))


def _pcm(mp3):
    result = subprocess.run(
        [ffmpeg_bin(), "-loglevel", "error", "-i", "pipe:0", "-f", "s16le",
         "-ac", "1", "-ar", str(SAMPLE_RATE), "pipe:1"],
        input=mp3, stdout=subprocess.PIPE, check=True)
    return result.stdout


def speak_phrases(text, out_path, rate=None, pitch=None, pause_scale=1.0, final_pause=0.0):
    """Пишет WAV с паузами между фразами и возвращает [(начало, конец, слово)].

    final_pause добавляет тишину перед последней фразой — пауза перед
    главным словом держит внимание сильнее самого текста.
    """
    rate, pitch = rate or RATE, pitch or PITCH
    chunks, words, cursor = [], [], 0.0
    parts = phrases(text)
    for index, phrase in enumerate(parts):
        mp3, spoken = _speak_retry(tts_text(phrase), rate, pitch)
        pcm = _pcm(mp3)
        keep = int((spoken[-1][1] + TAIL_KEEP) * SAMPLE_RATE) * 2
        pcm = pcm[:keep]
        chunks.append(pcm)
        words += [(cursor + s, cursor + e, w) for s, e, w in spoken]
        cursor += len(pcm) / 2.0 / SAMPLE_RATE
        if index + 1 < len(parts):
            pause = PAUSES.get(phrase.rstrip()[-1:], 0.25) * pause_scale
            if index + 2 == len(parts):
                pause += final_pause
            chunks.append(b"\x00\x00" * int(pause * SAMPLE_RATE))
            cursor += pause

    with wave.open(out_path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(b"".join(chunks))
    return words


async def _speak_whole(text, out_path):
    audio, words = await _speak(text, RATE, PITCH)
    with open(out_path, "wb") as f:
        f.write(audio)
    return words


def speak(text, out_path):
    """Сплошная озвучка одним куском — для старого формата роликов."""
    last = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return asyncio.run(_speak_whole(text, out_path))
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < ATTEMPTS:
                time.sleep(RETRY_DELAY * attempt)
    raise RuntimeError("озвучка не удалась после %d попыток: %s" % (ATTEMPTS, last))


def main():
    if len(sys.argv) < 3:
        print("Использование: python voice.py \"текст\" файл.wav")
        return 1
    words = speak_phrases(sys.argv[1], sys.argv[2])
    print("фразы:", " | ".join(phrases(sys.argv[1])))
    for start, end, word in words:
        print("%6.2f  %6.2f  %s" % (start, end, word))
    return 0


if __name__ == "__main__":
    sys.exit(main())
