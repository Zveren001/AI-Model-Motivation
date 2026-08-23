# -*- coding: utf-8 -*-
"""Чтение .env и общие пути проекта."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT, ".env")

QUOTES = os.path.join(ROOT, "quotes", "quotes.json")
OUTPUT = os.path.join(ROOT, "output")


def load_env(path=ENV_PATH):
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.strip().strip('"').strip("'")
            if val:
                values[key.strip()] = val
    return values


ENV = load_env()


def set_env(name, value, path=ENV_PATH):
    """Заменяет одно значение в .env, остальные строки и комментарии не трогает."""
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    prefix = "%s=" % name
    for i, line in enumerate(lines):
        if line.strip().startswith(prefix):
            lines[i] = "%s%s\n" % (prefix, value)
            break
    else:
        lines.append("%s%s\n" % (prefix, value))

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    ENV[name] = value


def get(name, default=None, required=False):
    value = ENV.get(name, os.environ.get(name, default))
    if required and not value:
        sys.exit("Не заполнено значение %s в файле .env" % name)
    return value
