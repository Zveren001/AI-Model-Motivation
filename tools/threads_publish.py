# -*- coding: utf-8 -*-
"""Публикация цитаты в Threads.

Схема как у Instagram: контейнер → ожидание обработки → публикация.
Токен и идентификатор отдельные, домен свой, лимит текста 500 символов.
Настройка описана в docs/threads-setup.md.
"""

import sys
import time
import urllib.error

import config
import meta_net

API = "https://graph.threads.net/v1.0"

TEXT_LIMIT = 500


def _call(method, path, params):
    url = "%s/%s" % (API, path)
    if method == "POST":
        return meta_net.post(url, params)
    return meta_net.get(url, params)


def wait_ready(container_id, token, attempts=15, delay=4):
    for i in range(attempts):
        time.sleep(delay)
        info = _call("GET", container_id,
                     {"fields": "status,error_message", "access_token": token})
        status = info.get("status")
        if status == "FINISHED":
            return True
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError("Threads не обработал контейнер: %s"
                               % info.get("error_message", status))
    raise RuntimeError("Контейнер Threads не обработался за отведённое время")


def publish(text, image_url, topic=None):
    """Публикует картинку с текстом. Возвращает id публикации."""
    user_id = config.get("THREADS_USER_ID", required=True)
    token = config.get("THREADS_ACCESS_TOKEN", required=True)

    if len(text) > TEXT_LIMIT:
        text = text[:TEXT_LIMIT - 1].rstrip() + "…"

    params = {
        "media_type": "IMAGE",
        "image_url": image_url,
        "text": text,
        "access_token": token,
    }
    if topic:
        params["topic_tag"] = topic

    creation_id = _call("POST", "%s/threads" % user_id, params)["id"]
    wait_ready(creation_id, token)

    result = _call("POST", "%s/threads_publish" % user_id, {
        "creation_id": creation_id,
        "access_token": token,
    })
    return result.get("id")


def main():
    if len(sys.argv) < 3:
        print("Использование: python threads_publish.py <текст> <ссылка на картинку>")
        return 1
    try:
        print(publish(sys.argv[1], sys.argv[2]))
    except (urllib.error.HTTPError, RuntimeError) as e:
        body = e.read().decode()[:400] if hasattr(e, "read") else str(e)
        sys.exit("Threads: %s" % body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
