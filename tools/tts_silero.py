# -*- coding: utf-8 -*-
"""Озвучка голосами Silero: синтез идёт отдельным процессом, тайминги слов считаются по слогам.

Модель живёт в своём окружении (SILERO_PYTHON, SILERO_MODEL): torch занимает
полгигабайта, и после выхода процесса память возвращается сборке ролика.

Silero не отдаёт время каждого слова, как edge-tts, поэтому внутри фразы слова
раскладываются по числу слогов. Фразы короткие, и на глаз расхождение незаметно.
"""

import json
import os
import subprocess
import sys
import tempfile
import wave

import config

PYTHON = config.get("SILERO_PYTHON", "/opt/silero/venv/bin/python")
MODEL = config.get("SILERO_MODEL", "/opt/silero/v5_5_ru.pt")
SAMPLE_RATE = 48000
RATES = ("x-slow", "slow", "medium", "fast", "x-fast")
VOWELS = "аеёиоуыэюя"

# Стык слов съедает заметную долю времени короткого слова, иначе односложные слова спешат
WORD_GAP = 0.35


def configured():
    return os.path.exists(PYTHON) and os.path.exists(MODEL)


def syllables(word):
    return max(1, sum(1 for ch in word.lower() if ch in VOWELS))


def word_times(text, start, duration):
    """Слова фразы на отрезке от start длиной duration, пропорционально слогам."""
    words = text.split()
    weights = [syllables(w) + WORD_GAP for w in words]
    total = sum(weights)
    out, cursor = [], start
    for word, weight in zip(words, weights):
        span = duration * weight / total
        out.append((cursor, cursor + span, word))
        cursor += span
    return out


def pauses_for(parts, pause_scale, final_pause):
    """Пауза после каждой фразы; перед последней добавляется пауза ожидания."""
    import voice  # локальный импорт: voice тянет edge_tts, а рабочему процессу он не нужен
    out = []
    for index, phrase in enumerate(parts):
        if index + 1 == len(parts):
            out.append(0.0)
            continue
        pause = voice.PAUSES.get(phrase.rstrip()[-1:], 0.25) * pause_scale
        if index + 2 == len(parts):
            pause += final_pause
        out.append(pause)
    return out


def run_worker(request):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(request, f, ensure_ascii=False)
        path = f.name
    try:
        done = subprocess.run([PYTHON, os.path.abspath(__file__), "--worker", path],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    finally:
        os.remove(path)
    if done.returncode:
        raise RuntimeError(done.stderr.decode("utf-8", "replace").strip()[-300:])
    return json.loads(done.stdout.decode("utf-8").strip().splitlines()[-1])


def speak_phrases(text, out_path, speaker="xenia", rate="medium", pause_scale=1.0, final_pause=0.0):
    """Пишет WAV с паузами между фразами и возвращает [(начало, конец, слово)]."""
    import voice  # локальный импорт: см. pauses_for
    if rate not in RATES:
        raise ValueError("темп %s не из %s" % (rate, ", ".join(RATES)))
    parts = voice.phrases(text)
    request = {"model": MODEL, "speaker": speaker, "rate": rate, "sample_rate": SAMPLE_RATE,
               "out": os.path.abspath(out_path),
               "phrases": [{"text": p, "pause": d}
                           for p, d in zip(parts, pauses_for(parts, pause_scale, final_pause))]}
    spans = run_worker(request)["phrases"]
    words = []
    for phrase, span in zip(parts, spans):
        words += word_times(phrase, span["start"], span["dur"])
    return words


def escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def worker(path):
    """Синтез в окружении Silero: пишет WAV и отдаёт родителю длительность каждой фразы."""
    import torch

    with open(path, encoding="utf-8") as f:
        request = json.load(f)
    torch.set_num_threads(1)
    model = torch.package.PackageImporter(request["model"]).load_pickle("tts_models", "model")
    model.to(torch.device("cpu"))

    rate, sample_rate = request["rate"], request["sample_rate"]
    chunks, spans, cursor = [], [], 0.0
    for item in request["phrases"]:
        ssml = '<speak><prosody rate="%s">%s</prosody></speak>' % (rate, escape(item["text"]))
        audio = model.apply_tts(ssml_text=ssml, speaker=request["speaker"],
                                sample_rate=sample_rate, put_accent=True, put_yo=True)
        pcm = (audio.clamp(-1, 1) * 32767).to(torch.int16).numpy().tobytes()
        duration = len(pcm) / 2.0 / sample_rate
        spans.append({"start": round(cursor, 3), "dur": round(duration, 3)})
        chunks.append(pcm)
        chunks.append(b"\x00\x00" * int(item["pause"] * sample_rate))
        cursor += duration + item["pause"]

    with wave.open(request["out"], "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(b"".join(chunks))
    print(json.dumps({"phrases": spans}))


def main():
    if "--worker" in sys.argv:
        worker(sys.argv[sys.argv.index("--worker") + 1])
        return 0
    if len(sys.argv) < 3:
        print("Использование: python tts_silero.py «текст» out.wav [голос] [темп]")
        return 1
    speaker = sys.argv[3] if len(sys.argv) > 3 else "xenia"
    rate = sys.argv[4] if len(sys.argv) > 4 else "medium"
    for start, end, word in speak_phrases(sys.argv[1], sys.argv[2], speaker, rate):
        print("%5.2f–%5.2f  %s" % (start, end, word))
    return 0


if __name__ == "__main__":
    sys.exit(main())
