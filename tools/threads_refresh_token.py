# -*- coding: utf-8 -*-
"""Продление токена Threads и определение идентификатора аккаунта.

Токен Threads отдельный от инстаграмного, живёт те же 60 дней и так же
молча перестаёт работать. Запускать раз в 50 дней вместе с ig_refresh_token.

Режим --whoami нужен на этапе настройки: идентификатор пользователя Threads
не совпадает с инстаграмным, а в интерфейсе Meta он не показан.
"""

import sys
import urllib.error
import urllib.parse

import config
import meta_net

REFRESH_URL = "https://graph.threads.net/refresh_access_token"
ME_URL = "https://graph.threads.net/v1.0/me"


def whoami(token=None):
    """Показывает id и ник аккаунта, которому принадлежит токен."""
    token = token or config.get("THREADS_ACCESS_TOKEN", required=True)
    params = urllib.parse.urlencode({"fields": "id,username", "access_token": token})
    try:
        data = meta_net.get("%s?%s" % (ME_URL, params))
    except urllib.error.HTTPError as e:
        sys.exit("Threads не принял токен: %s\n%s" % (e.code, e.read().decode()[:600]))

    print("THREADS_USER_ID=%s" % data.get("id"))
    print("Аккаунт: @%s" % data.get("username"))
    return data


def refresh():
    token = config.get("THREADS_ACCESS_TOKEN", required=True)
    params = urllib.parse.urlencode({
        "grant_type": "th_refresh_token",
        "access_token": token,
    })
    try:
        data = meta_net.get("%s?%s" % (REFRESH_URL, params))
    except urllib.error.HTTPError as e:
        sys.exit("Не удалось продлить токен Threads: %s\n%s"
                 % (e.code, e.read().decode()[:600]))

    new_token = data.get("access_token")
    if not new_token:
        sys.exit("Ответ без токена: %s" % data)

    config.set_env("THREADS_ACCESS_TOKEN", new_token)
    print("Токен Threads продлён, действует ещё %d дней"
          % (int(data.get("expires_in", 0)) // 86400))
    return new_token


def main():
    if "--whoami" in sys.argv:
        token = None
        for a in sys.argv[1:]:
            if not a.startswith("--"):
                token = a
        if not token and not config.get("THREADS_ACCESS_TOKEN"):
            token = input("Вставь токен Threads: ").strip()
        whoami(token)
        return 0

    refresh()
    return 0


if __name__ == "__main__":
    sys.exit(main())
