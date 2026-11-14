#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Простой консольный эмулятор микроволновой печи «МикроКонтроль-МВ».
Пошаговый диалог: на каждом шаге предлагаются варианты выбора.
Только стандартная библиотека Python 3.
"""

import queue
import sys
import threading
import time
from enum import Enum


# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

TIME_SCALE = 5.0
PWM_PERIOD = 20
LIGHT_TIMEOUT = 10

POWER_LEVELS = {
    "P20":  (160, 0.20),
    "P40":  (320, 0.40),
    "P60":  (480, 0.60),
    "P80":  (640, 0.80),
    "P100": (800, 1.00),
}


# ---------------------------------------------------------------------------
# Состояния
# ---------------------------------------------------------------------------

class State(Enum):
    IDLE = "Ожидание"
    SETUP = "Настройка"
    COOKING = "Приготовление"
    PAUSE = "Пауза"
    FINISH = "Завершено"


# ---------------------------------------------------------------------------
# Фоновое чтение stdin
# ---------------------------------------------------------------------------

_input_queue: "queue.Queue[str]" = queue.Queue()


def _input_reader():
    while True:
        try:
            line = input()
        except EOFError:
            _input_queue.put("")
            return
        _input_queue.put(line)


def start_input_reader():
    t = threading.Thread(target=_input_reader, daemon=True)
    t.start()


def read_input(prompt=""):
    if prompt:
        print(prompt, end="", flush=True)
    return _input_queue.get()


# ---------------------------------------------------------------------------
# Эмулятор
# ---------------------------------------------------------------------------

class Microwave:
    """Эмулятор микроволновки."""

    def __init__(self):
        self.state = State.IDLE
        self.power = "P100"
        self.target_time = 0.0
        self.remaining_time = 0.0
        self.door_open = False
        self.no_rot = False
        self.magnetron_on = False
        self.turntable_on = False
        self.light_on = True
        self.light_timer = LIGHT_TIMEOUT
        self.pwm_accum = 0.0
        self.virtual_time = 0.0

    def fmt_time(self, seconds):
        seconds = int(max(0, seconds))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def power_watts(self):
        return POWER_LEVELS[self.power][0]

    def apply_event_light(self):
        self.light_on = True
        self.light_timer = LIGHT_TIMEOUT

    def show_status(self):
        door = "ОТКР" if self.door_open else "ЗАКР"
        mag = "ВКЛ" if self.magnetron_on else "ВЫКЛ"
        rot = "ВКЛ" if self.turntable_on else "ВЫКЛ"
        nr = "ВКЛ" if self.no_rot else "ВЫКЛ"

        if self.state in (State.IDLE, State.SETUP):
            display_time = self.target_time
        elif self.state == State.FINISH:
            display_time = 0
        else:
            display_time = self.remaining_time

        print("\n" + "-" * 46)
        print(f"  Состояние : {self.state.value}")
        print(f"  Дисплей   : {self.fmt_time(display_time)}")
        print(f"  Дверь: {door}   Магнетрон: {mag}   Стол: {rot}   NO ROT: {nr}")
        print(f"  Мощность  : {self.power} ({self.power_watts()} Вт)")
        print("-" * 46)

    def tick(self, real_dt):
        dt = real_dt * TIME_SCALE
        self.virtual_time += dt

        if self.light_timer > 0:
            self.light_timer -= dt
            if self.light_timer <= 0:
                self.light_on = False
                self.light_timer = 0

        if self.state == State.COOKING:
            # Открытие дверцы во время готовки → пауза
            if self.door_open:
                self.state = State.PAUSE
                self.magnetron_on = False
                self.turntable_on = False
                self.apply_event_light()
                return

            duty = POWER_LEVELS[self.power][1]
            self.pwm_accum += dt
            if self.pwm_accum >= PWM_PERIOD:
                self.pwm_accum -= PWM_PERIOD
            self.magnetron_on = self.pwm_accum < PWM_PERIOD * duty

            self.remaining_time -= dt
            if self.remaining_time <= 0:
                self.remaining_time = 0
                self.magnetron_on = False
                self.turntable_on = False
                self.state = State.FINISH
                self.no_rot = False
                self.apply_event_light()

    # --- действия ---------------------------------------------------------

    def start_cooking(self):
        if self.door_open:
            print("\n  [!] Дверь открыта — запуск невозможен.")
            return False
        if self.target_time <= 0:
            print("\n  [!] Время не задано.")
            return False
        self.remaining_time = float(self.target_time)
        self.magnetron_on = True
        self.turntable_on = not self.no_rot
        self.pwm_accum = 0.0
        self.state = State.COOKING
        self.apply_event_light()
        print("\n  [OK] Приготовление запущено.")
        return True

    def pause_cooking(self):
        if self.state == State.COOKING:
            self.state = State.PAUSE
            self.magnetron_on = False
            self.turntable_on = False
            self.apply_event_light()
            print("\n  [OK] Пауза.")

    def resume_cooking(self):
        if self.state == State.PAUSE and not self.door_open:
            self.state = State.COOKING
            self.magnetron_on = True
            self.turntable_on = not self.no_rot
            self.apply_event_light()
            print("\n  [OK] Продолжение.")
        elif self.door_open:
            print("\n  [!] Дверь открыта — сначала закройте.")

    def open_door(self):
        """Открыть дверцу. Если шла готовка — автоматически пауза."""
        if self.door_open:
            print("\n  [!] Дверь уже открыта.")
            return
        self.door_open = True
        self.apply_event_light()
        if self.state == State.COOKING:
            self.pause_cooking()
            print("  Дверь открыта во время готовки — пауза.")
        else:
            print("\n  Дверь открыта.")

    def close_door(self):
        if not self.door_open:
            print("\n  [!] Дверь уже закрыта.")
            return
        self.door_open = False
        self.apply_event_light()
        print("\n  Дверь закрыта.")

    def toggle_door(self):
        if self.door_open:
            self.close_door()
        else:
            self.open_door()

    def reset(self):
        self.state = State.IDLE
        self.target_time = 0.0
        self.remaining_time = 0.0
        self.magnetron_on = False
        self.turntable_on = False
        self.no_rot = False
        self.pwm_accum = 0.0
        self.apply_event_light()


# ---------------------------------------------------------------------------
# Вспомогательные функции диалога
# ---------------------------------------------------------------------------

def ask_choice(prompt, options):
    print(f"\n{prompt}")
    for i, (_, label) in enumerate(options, 1):
        print(f"  {i}. {label}")
    while True:
        raw = read_input("Ваш выбор: ").strip()
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx][0]
        print("  [!] Неверный ввод, попробуйте снова.")


def ask_int(prompt, lo, hi):
    while True:
        raw = read_input(f"{prompt} ({lo}..{hi}): ").strip()
        if raw.lstrip("-").isdigit():
            val = int(raw)
            if lo <= val <= hi:
                return val
        print("  [!] Неверное число.")


def print_power_table():
    print("\n  Доступные уровни мощности (номинал магнетрона 800 Вт):")
    print("  " + "-" * 52)
    print(f"  {'Код':<6}{'Скважность':<18}{'Средняя мощность':<20}")
    print("  " + "-" * 52)
    for code, (watts, duty) in POWER_LEVELS.items():
        on_sec = int(PWM_PERIOD * duty)
        off_sec = PWM_PERIOD - on_sec
        cycle = f"{on_sec} с вкл / {off_sec} с выкл"
        print(f"  {code:<6}{cycle:<18}{watts:>3} Вт ({int(duty * 100)}%)")
    print("  " + "-" * 52)


def dialog_power(emu):
    print_power_table()
    options = []
    for code in POWER_LEVELS:
        watts = POWER_LEVELS[code][0]
        mark = "  ← текущая" if code == emu.power else ""
        options.append((code, f"{code} — {watts} Вт{mark}"))
    chosen = ask_choice("Выберите уровень мощности:", options)
    emu.power = chosen
    emu.apply_event_light()
    print(f"\n  Мощность установлена: {emu.power} ({emu.power_watts()} Вт)")


# ---------------------------------------------------------------------------
# Ожидание во время приготовления
# ---------------------------------------------------------------------------

def wait_cooking(emu):
    print("\n  Идёт приготовление. Enter — меню (пауза/дверь/прервать).")
    last_time = time.time()
    last_print = 0.0

    while emu.state == State.COOKING:
        now = time.time()
        dt = now - last_time
        last_time = now
        emu.tick(dt)

        if now - last_print >= 0.1:
            last_print = now
            mag = "ВКЛ " if emu.magnetron_on else "ВЫКЛ"
            rot = "ВКЛ " if emu.turntable_on else "ВЫКЛ"
            print(
                f"\r  Осталось: {emu.fmt_time(emu.remaining_time)}  "
                f"| Магнетрон: {mag} | Стол: {rot}  ",
                end="", flush=True,
            )

        if _enter_pressed():
            print()
            return True

        time.sleep(0.05)

    print()
    return False


def _enter_pressed():
    try:
        _input_queue.get_nowait()
        return True
    except queue.Empty:
        return False


# ---------------------------------------------------------------------------
# Диалоги
# ---------------------------------------------------------------------------

def dialog_idle(emu):
    choice = ask_choice(
        "Что будем делать?",
        [
            ("setup", "Настроить программу (время, мощность)"),
            ("quick", "Быстрый старт (30 с, текущая мощность)"),
            ("door",  "Открыть/закрыть дверь"),
            ("norot", "Переключить NO ROT"),
            ("exit",  "Выход"),
        ],
    )
    if choice == "setup":
        emu.state = State.SETUP
    elif choice == "quick":
        emu.target_time = 30
        if emu.start_cooking():
            if not wait_cooking(emu):
                # готовка закончилась сама или ушли в паузу/меню
                if emu.state == State.FINISH:
                    print("\n  >>> ВРЕМЯ ВЫШЛО. ПРИГОТОВЛЕНИЕ ЗАВЕРШЕНО.")
    elif choice == "door":
        emu.toggle_door()
    elif choice == "norot":
        emu.no_rot = not emu.no_rot
        emu.apply_event_light()
        print(f"\n  NO ROT: {'вкл' if emu.no_rot else 'выкл'}.")
    elif choice == "exit":
        return False
    return True


def dialog_setup(emu):
    power_list = "  ".join(
        f"{code}={watts}Вт" for code, (watts, _) in POWER_LEVELS.items()
    )
    print(f"\n  Мощности на выбор: {power_list}")

    choice = ask_choice(
        "Настройка программы:",
        [
            ("time",  f"Задать время (сейчас {emu.fmt_time(emu.target_time)})"),
            ("power", f"Задать мощность (сейчас {emu.power} — {emu.power_watts()} Вт)"),
            ("norot", f"Переключить NO ROT (сейчас {'вкл' if emu.no_rot else 'выкл'})"),
            ("door",  "Открыть/закрыть дверь"),
            ("start", "СТАРТ"),
            ("reset", "Сброс в ожидание"),
        ],
    )
    if choice == "time":
        emu.target_time = ask_int("Время в секундах", 1, 3600)
        emu.apply_event_light()
        print(f"\n  Время: {emu.fmt_time(emu.target_time)}")
    elif choice == "power":
        dialog_power(emu)
    elif choice == "norot":
        emu.no_rot = not emu.no_rot
        emu.apply_event_light()
        print(f"\n  NO ROT: {'вкл' if emu.no_rot else 'выкл'}.")
    elif choice == "door":
        emu.toggle_door()
    elif choice == "start":
        if emu.start_cooking():
            if not wait_cooking(emu) and emu.state == State.FINISH:
                print("\n  >>> ВРЕМЯ ВЫШЛО. ПРИГОТОВЛЕНИЕ ЗАВЕРШЕНО.")
    elif choice == "reset":
        emu.reset()


def dialog_cooking(emu):
    """Меню, открываемое по Enter во время приготовления."""
    choice = ask_choice(
        "Приготовление идёт. Что делаем?",
        [
            ("pause",   "Пауза (сохранить время)"),
            ("door",    "Открыть дверцу (пауза)"),
            ("abort",   "Прервать и сбросить в ожидание"),
            ("resume",  "Продолжить (вернуться к готовке)"),
        ],
    )
    if choice == "pause":
        emu.pause_cooking()
    elif choice == "door":
        emu.open_door()
    elif choice == "abort":
        emu.reset()
        print("\n  Приготовление прервано пользователем.")
    elif choice == "resume":
        if not wait_cooking(emu) and emu.state == State.FINISH:
            print("\n  >>> ВРЕМЯ ВЫШЛО. ПРИГОТОВЛЕНИЕ ЗАВЕРШЕНО.")


def dialog_pause(emu):
    """Меню состояния «Пауза»."""
    door_state = "открыта" if emu.door_open else "закрыта"
    choice = ask_choice(
        "Пауза:",
        [
            ("resume", "Продолжить (только если дверца закрыта)"),
            ("door",   f"Открыть/закрыть дверцу (сейчас {door_state})"),
            ("abort",  "Прервать и сбросить в ожидание"),
        ],
    )
    if choice == "resume":
        if emu.door_open:
            print("\n  [!] Дверца открыта — сначала закройте её.")
        else:
            emu.resume_cooking()
            if emu.state == State.COOKING:
                if not wait_cooking(emu) and emu.state == State.FINISH:
                    print("\n  >>> ВРЕМЯ ВЫШЛО. ПРИГОТОВЛЕНИЕ ЗАВЕРШЕНО.")
    elif choice == "door":
        emu.toggle_door()
    elif choice == "abort":
        emu.reset()
        print("\n  Приготовление прервано пользователем.")


def dialog_finish(emu):
    print("\n  *** ПРИГОТОВЛЕНИЕ ЗАВЕРШЕНО ***")
    choice = ask_choice(
        "Готово!",
        [
            ("reset", "Сброс в ожидание"),
            ("exit",  "Выход"),
        ],
    )
    if choice == "reset":
        emu.reset()
    elif choice == "exit":
        return False
    return True


# ---------------------------------------------------------------------------
# Главный цикл
# ---------------------------------------------------------------------------

def main():
    emu = Microwave()
    start_input_reader()
    last_time = time.time()

    print("=== МикроКонтроль-МВ ===")
    print("Пошаговый диалог: выбирайте пункты меню цифрами.")

    try:
        running = True
        while running:
            now = time.time()
            emu.tick(now - last_time)
            last_time = now

            emu.show_status()

            if emu.state == State.IDLE:
                running = dialog_idle(emu)
            elif emu.state == State.SETUP:
                dialog_setup(emu)
            elif emu.state == State.COOKING:
                dialog_cooking(emu)
            elif emu.state == State.PAUSE:
                dialog_pause(emu)
            elif emu.state == State.FINISH:
                running = dialog_finish(emu)

            time.sleep(0.02)

        print("\nВыход. До встречи!")

    except KeyboardInterrupt:
        print("\n\nПрервано пользователем. Выход.")
    except Exception as exc:
        print(f"\nКритическая ошибка: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()