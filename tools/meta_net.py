# -*- coding: utf-8 -*-
"""Сетевой слой для запросов к API Meta в обход DNS-блокировки.

Российские провайдеры отдают NXDOMAIN на graph.instagram.com и
graph.facebook.com, подменяя ответ даже при обращении к публичным DNS.
Сам трафик при этом не блокируется, поэтому имена резолвятся через
DNS-over-HTTPS, а соединение открывается по полученному адресу с
правильным SNI. Так публикация работает без VPN.
"""

import http.client
import json
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request

DOH_URL = "https://cloudflare-dns.com/dns-query?name=%s&type=A"
_cache = {}


def resolve(host):
    """Резолвит имя через DNS-over-HTTPS, результат кешируется на время запуска."""
    if host in _cache:
        return _cache[host]

    req = urllib.request.Request(DOH_URL % host, headers={"accept": "application/dns-json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())

    addresses = [a["data"] for a in data.get("Answer", []) if a.get("type") == 1]
    if not addresses:
        raise RuntimeError("Не удалось определить адрес %s" % host)

    _cache[host] = addresses[0]
    return addresses[0]


class _Connection(http.client.HTTPSConnection):
    def connect(self):
        sock = socket.create_connection((resolve(self.host), self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _Handler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_Connection, req)


_opener = urllib.request.build_opener(_Handler)


def get(url, params=None, timeout=60):
    """GET-запрос к API, возвращает разобранный JSON."""
    if params:
        url = "%s?%s" % (url, urllib.parse.urlencode(params))
    with _opener.open(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def post(url, params, timeout=120):
    """POST-запрос к API, возвращает разобранный JSON."""
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with _opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def check():
    """Проверяет, что домены Meta доступны."""
    for host in ("graph.instagram.com", "graph.facebook.com"):
        try:
            print("%-22s -> %s" % (host, resolve(host)))
        except Exception as e:
            print("%-22s недоступен: %s" % (host, e))


if __name__ == "__main__":
    check()
