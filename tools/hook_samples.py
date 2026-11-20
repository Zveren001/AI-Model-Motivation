# -*- coding: utf-8 -*-
"""Образцы зацепа с первого кадра, каждая фраза в двух размещениях, заставкой и заголовком"""

import html
import os
import subprocess
import sys
import urllib.parse

import compose
import config
import samples
import typefx

OUT = config.get("HOOK_SAMPLES_DIR", r"C:\Users\Zveren001\Desktop\MotivationHooks")
MANIFEST = os.path.join(config.OUTPUT, "hook_samples_manifest.json")
PLACES = ("заставка", "заголовок")

PHRASES = [
    ("Долго думаешь, стоит ли? Скорее всего, не стоит.", "Сомневаешься? Вот ответ",
     "person standing crossroads", "pechat_slovami", "Leda", "dark"),
    ("Доброта — не слабость, а выбор сильных.", "Тебя называют слишком добрым?",
     "helping elderly woman", "slova_proyavlyayutsya", "нет", "blur"),
    ("Проверь факты: тревога питается домыслами.", "Что делать, если тревожно",
     "reading documents desk", "pechat_posimvolno", "Enceladus", "bw"),
    ("Если тебя ценят, только когда удобно, — тебя не ценят.", "Проверь, ценят ли тебя",
     "woman alone window cup", "slova_snizu", "нет", "warm"),
    ("Уточни, прежде чем обидеться.", "Одно правило против ссор",
     "reading text message", "pechat_strokami", "Leda", "dark"),
    ("Если после встречи внутри пусто — это не твои люди.", "Как понять, что люди не твои",
     "woman walking city evening", "shtorka_po_strokam", "нет", "zoom"),
]


def first_frame(number, video):
    """Первый кадр ролика, именно его зритель видит до решения смахнуть"""
    folder = os.path.join(OUT, "первый кадр")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "%02d.jpg" % number)
    subprocess.run([compose.ffmpeg_bin(), "-y", "-loglevel", "error", "-i", video,
                    "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "3", path], check=True)
    return "первый кадр/%02d.jpg" % number


def build(numbers):
    manifest = samples.load_json(MANIFEST, {})
    os.makedirs(OUT, exist_ok=True)
    taken = set()
    for index, (text, hook, query, effect, voice, grade) in enumerate(PHRASES):
        clip, chosen = samples.clip_for(query, taken)
        taken.add(chosen["id"])
        for k, place in enumerate(PLACES):
            number = index * 2 + k + 1
            if number not in numbers:
                continue
            name = "%02d · %s · %s · голос %s.mp4" % (number, place, typefx.NAMES[effect], voice)
            duration, spoken = compose.render(text, os.path.join(OUT, name), clip, effect, grade,
                                              "тень", voice, seed=index, hook=hook, hook_place=place)
            manifest[str(number)] = {"file": name, "text": text, "hook": hook, "place": place,
                                     "effect": effect, "voice": spoken, "grade": grade,
                                     "clip_id": chosen["id"], "duration": duration}
            samples.save_json(MANIFEST, manifest)
            print("%02d готов: %.1f с, %s, голос %s" % (number, duration, place, spoken))
    write_index(manifest)


def write_index(manifest):
    cards = []
    for key in sorted(manifest, key=int):
        row, n = manifest[key], int(key)
        cards.append(CARD % {
            "n": n, "src": urllib.parse.quote(row["file"]),
            "poster": urllib.parse.quote(first_frame(n, os.path.join(OUT, row["file"]))),
            "hook": html.escape(row["hook"]), "text": html.escape(row["text"]),
            "place": row["place"], "effect": typefx.NAMES[row["effect"]],
            "voice": row["voice"], "duration": row["duration"]})
    with open(os.path.join(OUT, "00 Просмотр.html"), "w", encoding="utf-8") as f:
        f.write(PAGE % {"count": len(cards), "cards": "".join(cards)})


CARD = """<article><div class="num">%(n)02d</div>
<video src="%(src)s" poster="%(poster)s" controls preload="none" playsinline></video>
<p class="hook">%(hook)s</p><p class="quote">%(text)s</p>
<dl><dt>Зацеп</dt><dd>%(place)s</dd><dt>Эффект</dt><dd>%(effect)s</dd>
<dt>Голос</dt><dd>%(voice)s</dd><dt>Длина</dt><dd>%(duration).1f с</dd></dl></article>"""

PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>Зацеп с первого кадра</title><style>
body{margin:0;background:#0f0f10;color:#e8e6e3;font:15px/1.5 system-ui,Segoe UI,sans-serif}
header{padding:28px 32px 8px}h1{margin:0 0 6px;font-size:24px}
header p{margin:0 0 6px;color:#a8a6a3;max-width:900px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:18px;padding:16px 32px 32px}
article{background:#18181a;border-radius:12px;padding:12px;position:relative}
.num{position:absolute;top:18px;left:18px;background:#000c;color:#fff;border-radius:6px;
padding:2px 8px;font-weight:600;z-index:1}
video{width:100%%;aspect-ratio:9/16;border-radius:8px;background:#000;display:block}
.hook{margin:10px 0 2px;color:#ffce80;font-weight:600}.quote{margin:0 0 6px;color:#fff}
dl{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;margin:0;font-size:13px}
dt{color:#8a8885}dd{margin:0}
</style></head><body><header><h1>Зацеп с первого кадра, %(count)d образцов</h1>
<p>Шесть ближайших фраз списка, каждая в двух вариантах. Нечётные номера идут заставкой, это крупная надпись в центре на первые 1,4 секунды, затем фраза. Чётные идут заголовком, он стоит над фразой с первого кадра до конца.</p>
<p>Картинка на карточке показывает первый кадр, именно его видит зритель, пока решает, смахнуть или нет. Голос читает только фразу. Отвечать удобно номерами, например «заголовок, 4 и 6 да, 2 другой зацеп».</p>
</header><div class="grid">%(cards)s</div></body></html>"""


def main():
    numbers = list(range(1, len(PHRASES) * len(PLACES) + 1))
    for a in sys.argv[1:]:
        if a.startswith("--only="):
            numbers = samples.parse_numbers(a.split("=", 1)[1])
    build(numbers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
