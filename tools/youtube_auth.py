# -*- coding: utf-8 -*-
"""Разовое получение refresh-токена YouTube.

Запускается один раз на машине с браузером: открывает согласие Google, ловит код
на локальном порту и меняет его на токены. Полученный refresh-токен кладётся
в .env и дальше работает без участия человека.

Google отключил старый способ с показом кода на странице, поэтому редирект идёт
на localhost и код принимает поднятый здесь же одноразовый сервер.
"""

import http.server
import io
import os
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

import config

AUTH = "https://accounts.google.com/o/oauth2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/youtube.upload"
PORT = 8723

_code = {}


class Catcher(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        _code.update({k: v[0] for k, v in params.items()})

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        ok = "code" in _code
        self.wfile.write((
            "<html><body style='font-family:sans-serif;padding:40px'>"
            "<h2>%s</h2><p>%s</p></body></html>"
            % ("Готово" if ok else "Не получилось",
               "Окно можно закрыть, возвращайтесь в терминал" if ok
               else "Код не пришёл: %s" % _code.get("error", "неизвестная причина"))
        ).encode("utf-8"))

    def log_message(self, *args):
        pass


def exchange(client_id, client_secret, code, redirect):
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(TOKEN, data=data)
    with urllib.request.urlopen(req, timeout=60) as resp:
        import json
        return json.loads(resp.read())


def main():
    client_id = config.get("YT_CLIENT_ID", required=True)
    client_secret = config.get("YT_CLIENT_SECRET", required=True)
    redirect = "http://localhost:%d" % PORT

    server = http.server.HTTPServer(("localhost", PORT), Catcher)
    threading.Thread(target=server.handle_request, daemon=True).start()

    url = AUTH + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    })

    print("Открываю согласие Google в браузере.")
    print("Если приложение не проверено — «Дополнительно» → «Перейти на страницу».")
    print()
    print(url)
    print()
    webbrowser.open(url)

    for _ in range(300):
        if _code:
            break
        import time
        time.sleep(1)
    server.server_close()

    if "code" not in _code:
        sys.exit("Код не получен: %s" % _code.get("error", "истекло время ожидания"))

    tokens = exchange(client_id, client_secret, _code["code"], redirect)
    refresh = tokens.get("refresh_token")
    if not refresh:
        sys.exit("Google не вернул refresh_token — повторите с prompt=consent")

    config.set_env("YT_REFRESH_TOKEN", refresh)
    print("Токен получен и записан в .env")
    print()
    print("Статус приложения на экране согласия должен быть «In production»:")
    print("в режиме «Testing» Google отзывает refresh-токен через семь дней.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
