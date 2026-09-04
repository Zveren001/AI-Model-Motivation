# -*- coding: utf-8 -*-
"""Озвучка текста голосом Светланы через edge-tts с таймингами слов.

Тайминги нужны субтитрам: слова на экране появляются в ритм речи, а не
абзацем. Сервис внешний, поэтому запрос повторяется несколько раз
с паузами, прежде чем сдаться.
"""

import asyncio
import sys
import time

import edge_tts

import config

VOICE = config.get("VOICE", "ru-RU-SvetlanaNeural")
RATE = config.get("VOICE_RATE", "+0%")
PITCH = config.get("VOICE_PITCH", "+0Hz")
ATTEMPTS = 3
RETRY_DELAY = 20


async def _speak(text, out_path):
    communicate = edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH,
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
    with open(out_path, "wb") as f:
        f.write(audio)
    return words


def speak(text, out_path):
    """Пишет mp3 и возвращает список (начало, конец, слово) в секундах."""
    last = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return asyncio.run(_speak(text, out_path))
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < ATTEMPTS:
                time.sleep(RETRY_DELAY * attempt)
    raise RuntimeError("озвучка не удалась после %d попыток: %s" % (ATTEMPTS, last))


def main():
    if len(sys.argv) < 3:
        print("Использование: python voice.py \"текст\" файл.mp3")
        return 1
    words = speak(sys.argv[1], sys.argv[2])
    for start, end, word in words:
        print("%6.2f  %6.2f  %s" % (start, end, word))
    print("слов: %d, длительность речи %.1f с" % (len(words), words[-1][1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
