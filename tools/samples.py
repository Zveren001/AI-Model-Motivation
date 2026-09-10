# -*- coding: utf-8 -*-
"""Образцы роликов на утверждение: 60 готовых вариантов в одной папке.

Варианты сгруппированы блоками, чтобы каждое измерение можно было оценить
отдельно: эффекты с голосом, эффекты без голоса, подачи голоса, обработки
фона, подачи текста и в конце — набор, которым я предлагаю вести канал.
Рядом с роликами кладутся страница просмотра и таблица для оценки.
"""

import csv
import json
import os
import subprocess
import sys
import urllib.parse

import compose
import config
import footage
import quotes_list
import typefx

OUT = config.get("SAMPLES_DIR", r"C:\Users\Zveren001\Desktop\MotivationReference")
MANIFEST = os.path.join(config.OUTPUT, "samples_manifest.json")
SEARCH_CACHE = os.path.join(footage.CACHE, "search_cache.json")

QUOTES = [
    ("Упади семь раз — встань восемь.", "упорство", "boxing training",
     "Что тяжелее: упасть или заставить себя встать?"),
    ("Страшно не потому, что трудно. Трудно, потому что страшно.", "смелость",
     "rock climbing", "Что тебя чаще останавливает: страх или сомнения?"),
    ("Нас тревожат не события, а наши мысли о них.", "тревога", "calm lake fog",
     "Что тревожит сильнее: то, что уже случилось, или то, что может случиться?"),
    ("Кто не знает, куда плывёт, тому не бывает попутного ветра.", "цель", "sailboat sea",
     "У тебя есть цель на этот год: да или пока ищу?"),
    ("Кто везде — тот нигде.", "фокус", "busy city crowd",
     "Что сильнее отвлекает: телефон или чужие просьбы?"),
    ("Жизнь длинна, если она наполнена.", "жизнь", "golden field sunset",
     "Последний месяц был наполненным или пролетел незаметно?"),
    ("Беден не тот, у кого мало, а тот, кому всё мало.", "деньги", "minimalist room sunlight",
     "Тебе чаще не хватает денег или времени?"),
    ("Пока мы откладываем жизнь, она проходит.", "время", "hourglass sand",
     "Что ты откладываешь дольше: спорт или важный разговор?"),
    ("Лучшая месть — не стать похожим на обидчика.", "характер", "ocean waves rocks",
     "Ты чаще прощаешь или просто перестаёшь общаться?"),
    ("Твоя жизнь такова, каковы твои мысли.", "мышление", "clouds timelapse",
     "Сегодня твои мысли скорее помогают или мешают?"),
    ("Хватит рассуждать, каким должен быть хороший человек. Будь им.", "характер",
     "helping hands", "Когда ты последний раз помог просто так: на этой неделе или давно?"),
    ("Кто знает других — умён. Кто знает себя — мудр.", "самопознание",
     "mountain lake reflection", "Кого понять сложнее: других или себя?"),
    ("Кто побеждает других — силён. Кто побеждает себя — могуч.", "дисциплина",
     "martial arts silhouette", "Что сложнее победить в себе: лень или страх?"),
    ("Неважно, как медленно ты идёшь, главное — не останавливаться.", "упорство",
     "hiker mountain trail", "Ты сейчас идёшь медленно или стоишь на месте?"),
    ("Все думают изменить мир, но никто не думает изменить себя.", "перемены",
     "city lights night aerial", "Что проще изменить: обстоятельства или себя?"),
    ("У кого есть «зачем» жить, выдержит почти любое «как».", "смысл", "lighthouse storm",
     "Твоё «зачем» — это люди или цель?"),
    ("Мало знать — надо применять. Мало хотеть — надо делать.", "действие",
     "craftsman hands workshop", "Чего тебе сейчас больше не хватает: знаний или действий?"),
    ("Безумие — делать одно и то же и ждать другого результата.", "перемены",
     "treadmill running", "Ты чаще меняешь подход или надеешься, что само сработает?"),
    ("Сравнение — вор радости.", "сравнение", "people walking silhouette",
     "Ты чаще сравниваешь себя с другими или с собой вчерашним?"),
    ("Свободен лишь тот, кто владеет собой.", "свобода", "bird flying sky",
     "Что держит тебя сильнее: привычки или эмоции?"),
    ("Сделанное лучше идеального.", "действие", "typing laptop hands",
     "Ты чаще доделываешь до конца или бесконечно улучшаешь?"),
    ("Худшее уже случалось, и ты справился.", "поддержка", "sunrise after storm",
     "Что помогло пережить трудный период: люди или время?"),
    ("Отложить на завтра — значит поручить это уставшему себе.", "прокрастинация",
     "tired man desk night", "Ты больше успеваешь утром или вечером?"),
    ("Самый дорогой страх — страх выглядеть глупо.", "страх", "stage spotlight",
     "Что пугает сильнее: ошибиться или показаться смешным?"),
    ("Не рисковать — тоже риск. Просто медленный.", "риск", "cliff diving",
     "Ты чаще жалеешь о сделанном или о несделанном?"),
    ("Уходи оттуда, где тебя делают меньше.", "границы", "woman walking away road",
     "Тебе проще уйти или остаться и терпеть?"),
    ("Из пустой чашки не нальёшь.", "забота", "tea pouring cup",
     "Как ты восстанавливаешься: сон или тишина?"),
    ("Скажи «нет» лишнему, чтобы сказать «да» важному.", "границы", "notebook dark desk",
     "Кому труднее отказать: друзьям или работе?"),
    ("Одиночество лучше плохой компании.", "окружение", "man sitting alone lake",
     "Тебе комфортнее одному или в компании?"),
    ("Считай каждый день отдельной жизнью.", "настоящее", "sunrise over city",
     "Сегодняшний день ты проживаешь или пережидаешь?"),
    ("Глаза боятся, а руки делают.", "действие", "pottery hands",
     "Что сейчас страшнее начать: новую работу или новый навык?"),
    ("Если хочешь быть счастливым, будь им.", "счастье", "sunlight through trees",
     "Счастье для тебя — это состояние или решение?"),
    ("Никто не обнимет необъятного.", "фокус", "ocean horizon aerial",
     "Ты берёшься за всё сразу или по одному делу?"),
    ("Если хочешь, чтобы у тебя было мало времени, ничего не делай.", "время",
     "clock ticking", "Когда время летит быстрее: в загруженные дни или в пустые?"),
    ("Главное — не лги самому себе.", "честность", "mirror reflection",
     "Кому врать сложнее: другим или себе?"),
    ("Мы не получили жизнь короткой — мы сделали её такой.", "время", "city timelapse sunset",
     "Куда уходит больше времени: на работу или на телефон?"),
    ("Делай, что должен, и будь что будет.", "ответственность", "forest path walking",
     "Что важнее: результат или то, что ты сделал всё, что мог?"),
    ("Иногда даже жить — уже смелость.", "поддержка", "rain window night",
     "Что держит тебя в тяжёлые дни: люди или цель?"),
    ("Нельзя дважды войти в одну и ту же реку.", "перемены", "river flowing",
     "Ты больше боишься перемен или того, что ничего не изменится?"),
    ("Характер человека — его судьба.", "характер", "storm clouds mountains",
     "Что сильнее влияет на жизнь: характер или обстоятельства?"),
    ("Сколько живёшь — столько учись, как жить.", "обучение", "old books library",
     "Чему ты научился за этот год: новому делу или чему-то о себе?"),
    ("Всё трудно, пока не станет легко.", "обучение", "learning guitar hands",
     "Что далось тяжелее всего в начале: спорт или учёба?"),
    ("Удача — это подготовка, встретившая возможность.", "труд", "sprinter starting blocks",
     "Во что ты веришь больше: в удачу или в подготовку?"),
    ("Хочешь идти быстро — иди один. Хочешь идти далеко — идите вместе.", "окружение",
     "friends hiking together", "Ты чаще идёшь к цели один или с кем-то?"),
    ("Дорогу осилит идущий.", "путь", "road mountains walking",
     "Ты сейчас в пути или только собираешься?"),
    ("Большинство бед, которых я боялся, так и не случились.", "тревога", "calm sea morning",
     "Твои страхи чаще сбываются или нет?"),
    ("Делай то, чего боишься, — и страх уйдёт.", "страх", "cliff jump water",
     "Какой страх ты проверил бы первым: выступать на публике или сменить работу?"),
    ("Кто доволен — тот богат.", "счастье", "morning coffee window",
     "Тебе чаще хватает того, что есть, или хочется большего?"),
    ("Не ошибается только тот, кто ничего не делает.", "ошибки", "welding sparks workshop",
     "Ты чаще ошибаешься или боишься ошибиться?"),
    ("Стыд за ошибку живёт дольше самой ошибки.", "ошибки", "rain puddle reflection",
     "Ты быстро отпускаешь ошибки или долго носишь их с собой?"),
    ("Спокойный ум видит решения, тревожный — угрозы.", "спокойствие", "zen stones water",
     "Что помогает успокоиться: прогулка или разговор?"),
    ("Ты не откладываешь дело — ты откладываешь жизнь.", "прокрастинация",
     "empty chair window", "Что ты откладываешь больше месяца: дело или решение?"),
    ("За внезапным успехом — годы, которых никто не видел.", "упорство",
     "athlete training night", "Ты больше веришь в талант или в годы работы?"),
    ("Остановиться — не значит сдаться.", "отдых", "hiker resting mountain view",
     "Ты позволяешь себе паузы или считаешь это слабостью?"),
    ("Уставший человек принимает плохие решения.", "отдых", "tired woman night city",
     "Ты принимаешь важные решения утром или вечером?"),
    ("Трудности закаляют ум, как труд — тело.", "характер", "blacksmith forge",
     "Что закалило тебя сильнее: работа или трудные времена?"),
    ("Сначала реши, кем хочешь быть. Потом делай, что нужно.", "цель", "road horizon sunrise",
     "Ты уже знаешь, кем хочешь быть, или ещё ищешь?"),
    ("Великое начинается с малого.", "привычки", "seedling growing",
     "С чего проще начать: с пяти минут в день или сразу с часа?"),
    ("Не жди подходящего момента — создай его.", "действие", "sunrise timelapse",
     "Ты чаще ждёшь момент или создаёшь его?"),
    ("Когда цель недостижима, не меняй цель — меняй шаги.", "цель", "mountain summit hiker",
     "Когда не получается, ты меняешь цель или способ?"),
]

# Сочетания 60 образцов в том виде, как их собирали; вспышку и плашку
# после утверждения убрали из движка, в их строках стоят замены
PLAN = [
    ("pechat_posimvolno", "обычный", "dark", "тень"),
    ("pechat_slovami", "обычный", "dark", "тень"),
    ("pechat_strokami", "обычный", "dark", "тень"),
    ("slova_proyavlyayutsya", "обычный", "dark", "тень"),
    ("slova_snizu", "обычный", "dark", "тень"),
    ("shtorka_po_strokam", "обычный", "dark", "тень"),
    ("pechat_posimvolno", "обычный", "dark", "тень"),
    ("slova_padayut", "обычный", "dark", "тень"),
    ("pechat_s_podsvetkoj", "обычный", "dark", "тень"),
    ("slova_vspyshkoj", "обычный", "dark", "тень"),
    ("pechat_posimvolno", "нет", "dark", "тень"),
    ("pechat_slovami", "нет", "dark", "тень"),
    ("pechat_strokami", "нет", "dark", "тень"),
    ("slova_proyavlyayutsya", "нет", "dark", "тень"),
    ("slova_snizu", "нет", "dark", "тень"),
    ("shtorka_po_strokam", "нет", "dark", "тень"),
    ("pechat_posimvolno", "нет", "dark", "тень"),
    ("slova_padayut", "нет", "dark", "тень"),
    ("pechat_s_podsvetkoj", "нет", "dark", "тень"),
    ("slova_vspyshkoj", "нет", "dark", "тень"),
    ("pechat_posimvolno", "обычный", "dark", "тень"),
    ("pechat_posimvolno", "медленный", "dark", "тень"),
    ("pechat_posimvolno", "бодрый", "dark", "тень"),
    ("pechat_posimvolno", "с акцентом", "dark", "тень"),
    ("pechat_posimvolno", "низкий", "dark", "тень"),
    ("slova_proyavlyayutsya", "обычный", "dark", "тень"),
    ("slova_proyavlyayutsya", "медленный", "dark", "тень"),
    ("slova_proyavlyayutsya", "бодрый", "dark", "тень"),
    ("slova_proyavlyayutsya", "с акцентом", "dark", "тень"),
    ("slova_proyavlyayutsya", "низкий", "dark", "тень"),
    ("slova_snizu", "обычный", "dark", "тень"),
    ("pechat_slovami", "обычный", "blur", "тень"),
    ("slova_padayut", "обычный", "bw", "тень"),
    ("pechat_s_podsvetkoj", "обычный", "warm", "тень"),
    ("slova_vspyshkoj", "обычный", "zoom", "тень"),
    ("pechat_strokami", "нет", "dark", "тень"),
    ("shtorka_po_strokam", "нет", "blur", "тень"),
    ("pechat_posimvolno", "нет", "bw", "тень"),
    ("pechat_posimvolno", "нет", "warm", "тень"),
    ("slova_proyavlyayutsya", "нет", "zoom", "тень"),
    ("pechat_posimvolno", "обычный", "dark", "тень"),
    ("slova_proyavlyayutsya", "нет", "blur", "тень"),
    ("slova_snizu", "с акцентом", "warm", "тень"),
    ("slova_padayut", "медленный", "zoom", "тень"),
    ("pechat_slovami", "обычный", "dark", "крупно"),
    ("shtorka_po_strokam", "нет", "blur", "крупно"),
    ("pechat_s_podsvetkoj", "с акцентом", "bw", "крупно"),
    ("slova_vspyshkoj", "бодрый", "warm", "крупно"),
    ("pechat_posimvolno", "низкий", "bw", "тень"),
    ("pechat_strokami", "нет", "zoom", "крупно"),
    ("pechat_posimvolno", "с акцентом", "blur", "тень"),
    ("slova_proyavlyayutsya", "нет", "dark", "тень"),
    ("slova_snizu", "с акцентом", "blur", "тень"),
    ("shtorka_po_strokam", "нет", "zoom", "тень"),
    ("slova_padayut", "с акцентом", "blur", "тень"),
    ("pechat_slovami", "нет", "dark", "тень"),
    ("slova_vspyshkoj", "с акцентом", "blur", "тень"),
    ("pechat_s_podsvetkoj", "нет", "zoom", "тень"),
    ("pechat_strokami", "с акцентом", "blur", "тень"),
    ("pechat_posimvolno", "нет", "dark", "тень"),
]

BLOCKS = [
    (1, 10, "Эффекты с голосом", "Все десять эффектов первых роликов, теперь в ритм голоса. Голос обычный, фон затемнён, текст с тенью — меняется только эффект."),
    (11, 20, "Эффекты без голоса", "Те же десять эффектов без голоса: только музыка и стук клавиш, как в старых роликах. Сравните с первым блоком."),
    (21, 30, "Подачи голоса", "Пять подач: обычная, медленная с длинными паузами, бодрая, с акцентной паузой перед последней фразой, ниже тоном. На печати по буквам и на проявлении слов."),
    (31, 40, "Обработка фона", "Затемнение, размытие, чёрно-белый, тёплый тон и медленный наезд камеры — с голосом и без."),
    (41, 50, "Подача текста", "Тень под текстом, полупрозрачная плашка и крупный текст выше центра."),
    (51, 60, "Как я предлагаю вести канал", "Мой вариант ленты: размытый или затемнённый фон, голос с акцентной паузой через ролик, лучшие эффекты по кругу. Так выглядели бы два с половиной дня публикаций."),
]


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def candidates(query):
    cache = load_json(SEARCH_CACHE, {})
    if query not in cache:
        videos = footage.search(query, config.get("PEXELS_API_KEY", required=True))
        cache[query] = [{"id": v["id"], "link": footage.best_file(v)["link"],
                         "author": v.get("user", {}).get("name", "")}
                        for v in videos
                        if 10 <= v.get("duration", 0) <= 40 and footage.best_file(v)]
        save_json(SEARCH_CACHE, cache)
    return cache[query]


def clip_for(query, taken, skip=0):
    """Клип под смысл цитаты: первый подходящий по запросу, не повторяющий соседей."""
    options = [c for c in candidates(query) if c["id"] not in taken]
    if not options:
        raise RuntimeError("по запросу «%s» не нашлось вертикального клипа" % query)
    chosen = options[min(skip, len(options) - 1)]
    path = os.path.join(footage.CACHE, "%d.mp4" % chosen["id"])
    if not os.path.exists(path):
        os.makedirs(footage.CACHE, exist_ok=True)
        footage.download(chosen["link"], path)
    return path, chosen


def file_name(number, effect, voice, grade, text_style):
    return "%02d · %s · голос %s · %s · %s.mp4" % (
        number, typefx.NAMES[effect], voice, compose.GRADE_NAMES[grade], text_style)


def build(numbers, rerolls):
    manifest = load_json(MANIFEST, {})
    os.makedirs(OUT, exist_ok=True)
    taken = {entry["clip_id"] for key, entry in manifest.items() if int(key) not in numbers}
    for number in numbers:
        text, topic, query, question = QUOTES[number - 1]
        effect, voice, grade, text_style = PLAN[number - 1]
        skip = rerolls.get(number, manifest.get(str(number), {}).get("skip", 0))
        clip, chosen = clip_for(query, taken, skip)
        taken.add(chosen["id"])
        name = file_name(number, effect, voice, grade, text_style)
        old = manifest.get(str(number), {}).get("file")
        if old and old != name and os.path.exists(os.path.join(OUT, old)):
            os.remove(os.path.join(OUT, old))
        duration = compose.render(text, os.path.join(OUT, name), clip, effect, grade,
                                  text_style, voice, seed=number)
        manifest[str(number)] = {
            "file": name, "text": text, "topic": topic, "query": query,
            "question": question, "effect": effect, "voice": voice, "grade": grade,
            "text_style": text_style, "clip_id": chosen["id"], "author": chosen["author"],
            "skip": skip, "duration": duration,
        }
        save_json(MANIFEST, manifest)
        print("%02d готов: %.1f с, клип %s — %s" % (number, duration, chosen["id"], text))
    write_index(manifest)


def poster(number, row):
    """Кадр с цитатой целиком для карточки: первый кадр ролика ещё без текста."""
    folder = os.path.join(OUT, "превью")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "%02d.jpg" % number)
    video = os.path.join(OUT, row["file"])
    if not os.path.exists(path) or os.path.getmtime(path) < os.path.getmtime(video):
        subprocess.run([compose.ffmpeg_bin(), "-y", "-loglevel", "error",
                        "-ss", "%.2f" % max(0.0, row["duration"] - 0.6), "-i", video,
                        "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "3", path],
                       check=True)
    return "превью/%02d.jpg" % number


def write_index(manifest):
    rows = [manifest[k] for k in sorted(manifest, key=int)]
    numbers = sorted(int(k) for k in manifest)
    with open(os.path.join(OUT, "00 Оценка.csv"), "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["№", "Файл", "Цитата", "Эффект", "Голос", "Фон", "Текст",
                         "Вопрос первым комментарием", "Утверждаю (да/нет)", "Комментарий"])
        for n, row in zip(numbers, rows):
            writer.writerow([n, row["file"], row["text"], typefx.NAMES[row["effect"]],
                             row["voice"], compose.GRADE_NAMES[row["grade"]],
                             row["text_style"], row["question"], "", ""])

    cards = []
    for first, last, title, note in BLOCKS:
        items = []
        for n, row in zip(numbers, rows):
            if first <= n <= last:
                items.append(CARD % {
                    "n": n, "src": urllib.parse.quote(row["file"]),
                    "poster": urllib.parse.quote(poster(n, row)),
                    "text": row["text"], "effect": typefx.NAMES[row["effect"]],
                    "voice": row["voice"], "grade": compose.GRADE_NAMES[row["grade"]],
                    "style": row["text_style"], "question": row["question"],
                    "duration": row["duration"]})
        if items:
            cards.append(BLOCK % {"first": first, "last": last, "title": title,
                                  "note": note, "items": "".join(items)})
    with open(os.path.join(OUT, "00 Просмотр всех вариантов.html"), "w", encoding="utf-8") as f:
        f.write(PAGE % {"count": len(rows), "blocks": "".join(cards)})


CARD = """<article><div class="num">%(n)02d</div>
<video src="%(src)s" poster="%(poster)s" controls preload="none" playsinline></video>
<p class="quote">%(text)s</p>
<dl><dt>Эффект</dt><dd>%(effect)s</dd><dt>Голос</dt><dd>%(voice)s</dd>
<dt>Фон</dt><dd>%(grade)s</dd><dt>Текст</dt><dd>%(style)s</dd>
<dt>Длина</dt><dd>%(duration).1f с</dd></dl>
<p class="ask"><span>Первый комментарий:</span> %(question)s</p></article>"""

BLOCK = """<section><h2>%(first)02d–%(last)02d · %(title)s</h2><p class="note">%(note)s</p>
<div class="grid">%(items)s</div></section>"""

PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>Образцы роликов на утверждение</title><style>
body{margin:0;background:#0f0f10;color:#e8e6e3;font:15px/1.5 system-ui,Segoe UI,sans-serif}
header{padding:28px 32px 8px}h1{margin:0 0 6px;font-size:24px}
header p{margin:0;color:#a8a6a3;max-width:900px}
section{padding:12px 32px 28px}h2{font-size:18px;margin:18px 0 4px}
.note{color:#a8a6a3;margin:0 0 14px;max-width:900px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:18px}
article{background:#18181a;border-radius:12px;padding:12px;position:relative}
.num{position:absolute;top:18px;left:18px;background:#000c;color:#fff;border-radius:6px;
padding:2px 8px;font-weight:600;z-index:1}
video{width:100%%;aspect-ratio:9/16;border-radius:8px;background:#000;display:block}
.quote{font-size:15px;margin:10px 0 6px;color:#fff}
dl{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;margin:0;font-size:13px}
dt{color:#8a8885}dd{margin:0}
.ask{font-size:13px;color:#cfcdca;margin:8px 0 0}.ask span{color:#8a8885}
</style></head><body><header><h1>Образцы роликов на утверждение — %(count)d шт.</h1>
<p>Каждый ролик готов к публикации. Номер ролика — в левом верхнем углу карточки.
Комментарии удобно писать номером: «17 — да, 23 — голос медленнее, 31 — нет».
Таблица «00 Оценка.csv» в этой же папке открывается в Excel, в ней есть колонки для отметки и комментария.
Призыва в роликах нет: под каждым после публикации появится первый комментарий от канала — он указан в карточке.</p>
</header>%(blocks)s</body></html>"""


QUEUE_DIR = os.path.join(config.OUTPUT, "queue")
EXCLUDED = {26: "цитату назвали непонятной"}


def approved_numbers():
    """Номера образцов с отметкой «да» в таблице оценки, кроме исключённых."""
    with open(os.path.join(OUT, "00 Оценка.csv"), encoding="utf-8-sig") as f:
        marks = {int(r["№"]): r["Утверждаю (да/нет)"].strip().lower()
                 for r in csv.DictReader(f, delimiter=";") if r["№"].strip().isdigit()}
    # №23 отмечен «нет» по ошибке — пользователь подтвердил, что это «да»
    marks[23] = "да"
    return sorted(n for n, v in marks.items() if v.startswith("да") and n not in EXCLUDED)


def build_queue():
    """Готовые одобренные ролики: файлы для сервера и привязка к фразам единого списка."""
    manifest = load_json(MANIFEST, {})
    if os.path.isdir(QUEUE_DIR):
        for name in os.listdir(QUEUE_DIR):
            os.remove(os.path.join(QUEUE_DIR, name))
    os.makedirs(QUEUE_DIR, exist_ok=True)
    videos = []
    for n in approved_numbers():
        row = manifest[str(n)]
        name = "%02d.mp4" % n
        with open(os.path.join(OUT, row["file"]), "rb") as src, \
                open(os.path.join(QUEUE_DIR, name), "wb") as dst:
            dst.write(src.read())
        videos.append({"sample": n, "file": name, "text": row["text"], "effect": row["effect"],
                       "voice": row["voice"], "grade": row["grade"],
                       "text_style": row["text_style"], "clip_id": row["clip_id"],
                       "duration": row["duration"]})
    missing = quotes_list.attach_videos(videos)
    print("Готовых роликов: %d, привязано к фразам списка: %d" % (len(videos), len(videos) - len(missing)))
    for video in missing:
        print("   в списке нет фразы образца №%02d: %s" % (video["sample"], video["text"]))


def parse_numbers(arg):
    out = []
    for part in arg.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += range(int(a), int(b) + 1)
        elif part:
            out.append(int(part))
    return out


def main():
    numbers, rerolls = list(range(1, len(QUOTES) + 1)), {}
    for a in sys.argv[1:]:
        if a.startswith("--only="):
            numbers = parse_numbers(a.split("=", 1)[1])
        elif a.startswith("--reroll="):
            for n in parse_numbers(a.split("=", 1)[1]):
                rerolls[n] = load_json(MANIFEST, {}).get(str(n), {}).get("skip", 0) + 1
            numbers = sorted(rerolls)
        elif a == "--index":
            write_index(load_json(MANIFEST, {}))
            return 0
        elif a == "--queue":
            build_queue()
            return 0
    build(numbers, rerolls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
