# -*- coding: utf-8 -*-
"""
Карточки иностранных слов (Kivy).
ПК:      pip install kivy certifi   ->   python main.py
Android: buildozer android debug deploy run
"""

import csv
import io
import os
import random
import ssl
import threading
import urllib.request

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.utils import platform

# ------------------------------- НАСТРОЙКИ -----------------------------------
# ID берётся из ссылки: docs.google.com/spreadsheets/d/ ВОТ_ЭТО /edit#gid=0
# https://docs.google.com/spreadsheets/d/
# 1NqYTZptRfKmse-s06uYiBU2yligHTtt4nW1cfQ6EEvg
# /edit?gid=0#gid=0
SHEET_ID = "1gyXl_R302y-mIeZlHlsYMlDGlR2DGNS7Bf5pajmuylA"
GID = "0"                      # номер листа (gid из ссылки)

COL_EN = "Английское значение"  # заголовки первой строки таблицы
COL_RU = "Русское значение"
COL_TR = "Транскрипция"

LOCAL_CSV = "words.csv"         # резервный словарь рядом с main.py (офлайн)
CSV_URL = "https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"

BG    = (0.07, 0.09, 0.13, 1)
BLUE  = (0.16, 0.45, 0.78, 1)
GREEN = (0.15, 0.65, 0.30, 1)
RED   = (0.80, 0.20, 0.20, 1)
# -----------------------------------------------------------------------------


def http_get(url, timeout=15):
    """Скачивание с сертификатами certifi (важно для Android)."""
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.read().decode("utf-8-sig", errors="replace")
    except ssl.SSLError:
        # на Android часто нет системных CA; данные публичные и только на чтение
        with urllib.request.urlopen(
            req, timeout=timeout, context=ssl._create_unverified_context()
        ) as r:
            return r.read().decode("utf-8-sig", errors="replace")


def parse_words(csv_text):
    """CSV -> список словарей. Понимает и запятую, и точку с запятой."""
    if not csv_text.strip():
        raise ValueError("пустой ответ")
    if csv_text.lstrip()[0] == "<":
        raise ValueError(
            "Google вернул HTML вместо CSV.\n"
            "Откройте доступ: «Все, у кого есть ссылка» → Читатель."
        )

    first = csv_text.splitlines()[0]
    delim = ";" if first.count(";") > first.count(",") else ","
    reader = csv.DictReader(io.StringIO(csv_text), delimiter=delim)

    fields = [(f or "").strip() for f in (reader.fieldnames or [])]
    if COL_EN not in fields or COL_RU not in fields:
        raise ValueError(
            f"Нужны заголовки «{COL_EN}» и «{COL_RU}».\nНайдено: {fields}"
        )

    words, seen = [], set()
    for raw in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items() if k}
        en, ru = row.get(COL_EN, ""), row.get(COL_RU, "")
        if not en or not ru:
            continue
        key = (en.lower(), ru.lower())
        if key in seen:            # убираем дубли
            continue
        seen.add(key)
        words.append({COL_EN: en, COL_RU: ru, COL_TR: row.get(COL_TR, "")})
    return words


class FlashcardApp(App):
    title = "Карточки слов"

    # ------------------------------ интерфейс -------------------------------
    def build(self):
        Window.clearcolor = BG
        if platform not in ("android", "ios"):
            Window.size = (400, 720)          # окошко «как телефон» на ПК

        self.words, self.buttons = [], []
        self.index = self.correct = self.answered = 0
        self.current_word = None

        self.root_box = BoxLayout(orientation="vertical",
                                  padding=dp(16), spacing=dp(10))
        self.reload_dictionary()
        return self.root_box

    @staticmethod
    def _wrap(widget, dx=0, dy=0):
        widget.bind(size=lambda i, v: setattr(i, "text_size", (v[0] - dx, v[1] - dy)))

    def make_button(self, text, color):
        btn = Button(
            text=text, font_size=sp(19), color=(1, 1, 1, 1),
            background_normal="", background_down="",
            background_disabled_normal="", background_disabled_down="",
            background_color=color, halign="center", valign="middle",
        )
        self._wrap(btn, dp(14), dp(8))
        return btn

    def show_message(self, text, retry=False):
        self.root_box.clear_widgets()
        lbl = Label(text=text, font_size=sp(17), halign="center", valign="middle",
                    color=(0.9, 0.9, 0.9, 1))
        lbl.bind(size=lambda i, v: setattr(i, "text_size", (v[0], None)))
        self.root_box.add_widget(lbl)
        if retry:
            btn = self.make_button("Повторить", BLUE)
            btn.size_hint_y = None
            btn.height = dp(56)
            btn.bind(on_press=lambda *_: self.reload_dictionary())
            self.root_box.add_widget(btn)

    def build_quiz(self):
        self.root_box.clear_widgets()

        top = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        self.progress_label = Label(text="", font_size=sp(15),
                                    color=(0.7, 0.7, 0.75, 1),
                                    halign="left", valign="middle")
        self._wrap(self.progress_label)
        top.add_widget(self.progress_label)
        refresh = self.make_button("⟳", BLUE)
        refresh.size_hint_x = None
        refresh.width = dp(52)
        refresh.bind(on_press=lambda *_: self.reload_dictionary())
        top.add_widget(refresh)
        self.root_box.add_widget(top)

        self.word_label = Label(text="", font_size=sp(34), bold=True,
                                size_hint_y=0.30, halign="center", valign="middle")
        self._wrap(self.word_label)
        self.root_box.add_widget(self.word_label)

        self.trans_label = Label(text="", font_size=sp(20), size_hint_y=0.12,
                                 color=(0.55, 0.8, 1, 1),
                                 halign="center", valign="middle")
        self._wrap(self.trans_label)
        self.root_box.add_widget(self.trans_label)

        self.buttons = []
        for _ in range(4):
            btn = self.make_button("", BLUE)
            btn.size_hint_y = 0.14
            btn.bind(on_press=self.check_answer)
            self.buttons.append(btn)
            self.root_box.add_widget(btn)

    # ------------------------------ загрузка --------------------------------
    def reload_dictionary(self, *args):
        Clock.unschedule(self.next_question)
        self.current_word = None
        self.show_message("Загрузка словаря…")
        threading.Thread(target=self._load_worker, daemon=True).start()

    def _load_worker(self):                      # работает НЕ в UI-потоке
        words, errors = [], []
        if SHEET_ID and "ВСТАВЬТЕ" not in SHEET_ID:
            try:
                words = parse_words(http_get(CSV_URL.format(sid=SHEET_ID, gid=GID)))
            except Exception as e:
                errors.append(f"Google Таблица: {e}")
        else:
            errors.append("SHEET_ID не задан")

        if not words:                            # офлайн-резерв
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), LOCAL_CSV)
            try:
                with open(path, encoding="utf-8-sig", newline="") as f:
                    words = parse_words(f.read())
            except FileNotFoundError:
                errors.append(f"нет файла {LOCAL_CSV}")
            except Exception as e:
                errors.append(f"{LOCAL_CSV}: {e}")

        self.on_loaded(words, errors)

    @mainthread
    def on_loaded(self, words, errors):
        if len(words) < 2:
            self.show_message(
                "Не удалось загрузить словарь.\n\n" + "\n\n".join(errors) +
                f"\n\nНужно минимум 2 заполненные строки\nс колонками «{COL_EN}» и «{COL_RU}».",
                retry=True,
            )
            return
        self.words = words
        random.shuffle(self.words)
        self.index = self.correct = self.answered = 0
        self.build_quiz()
        self.next_question()

    # ------------------------------- логика ---------------------------------
    def next_question(self, *args):
        if not self.words:
            return
        if self.index >= len(self.words):
            self.index = 0
            random.shuffle(self.words)

        self.current_word = self.words[self.index]
        correct = self.current_word[COL_RU]

        self.progress_label.text = (
            f"{self.index + 1} / {len(self.words)}    верно: {self.correct} из {self.answered}"
        )
        self.word_label.text = self.current_word[COL_EN]
        self.trans_label.text = self.current_word[COL_TR]

        # только УНИКАЛЬНЫЕ переводы, иначе варианты повторяются
        pool = list({w[COL_RU] for w in self.words if w[COL_RU] != correct})
        options = [correct] + random.sample(pool, min(3, len(pool)))
        random.shuffle(options)

        for i, btn in enumerate(self.buttons):
            if i < len(options):
                btn.text = options[i]
                btn.opacity = 1
                btn.disabled = False
                btn.background_color = BLUE
            else:                       # словарик маленький — прячем лишние
                btn.text = ""
                btn.opacity = 0
                btn.disabled = True

    def check_answer(self, instance):
        if self.current_word is None or instance.disabled or not instance.text:
            return
        for btn in self.buttons:
            btn.disabled = True

        correct = self.current_word[COL_RU]
        self.answered += 1
        if instance.text == correct:
            self.correct += 1
            instance.background_color = GREEN
            delay = 0.7
        else:
            instance.background_color = RED
            for btn in self.buttons:
                if btn.text == correct:
                    btn.background_color = GREEN
            delay = 1.6

        self.index += 1
        Clock.schedule_once(self.next_question, delay)


if __name__ == "__main__":
    FlashcardApp().run()