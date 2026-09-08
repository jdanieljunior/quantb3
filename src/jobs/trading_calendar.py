"""Calendário operacional da B3 usado pela orquestração dos jobs.

O calendário decide quando um job pode rodar. A existência do fechamento no
banco continua sendo validada antes de qualquer operação financeira simulada.
"""

from __future__ import annotations

from datetime import date, timedelta


def _easter_sunday(year: int) -> date:
    """Calcula a Páscoa gregoriana (algoritmo de Meeus/Jones/Butcher)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def b3_holidays(year: int) -> set[date]:
    """Retorna os dias sem sessão regular de negociação da B3 no ano.

    Quarta-feira de Cinzas e vésperas com sessão reduzida permanecem como
    pregão, pois possuem fechamento diário.
    """
    easter = _easter_sunday(year)
    return {
        date(year, 1, 1),
        easter - timedelta(days=48),  # segunda de Carnaval
        easter - timedelta(days=47),  # terça de Carnaval
        easter - timedelta(days=2),   # Sexta-feira Santa
        date(year, 4, 21),            # Tiradentes
        date(year, 5, 1),             # Dia do Trabalho
        easter + timedelta(days=60),  # Corpus Christi
        date(year, 9, 7),             # Independência
        date(year, 10, 12),           # Nossa Senhora Aparecida
        date(year, 11, 2),            # Finados
        date(year, 11, 15),           # Proclamação da República
        date(year, 11, 20),           # Consciência Negra
        date(year, 12, 25),           # Natal
    }


def is_b3_trading_day(day: date) -> bool:
    """Informa se ``day`` é um pregão regular esperado na B3."""
    return day.weekday() < 5 and day not in b3_holidays(day.year)


def next_b3_trading_day(day: date) -> date:
    """Retorna o primeiro pregão estritamente posterior a ``day``."""
    candidate = day + timedelta(days=1)
    while not is_b3_trading_day(candidate):
        candidate += timedelta(days=1)
    return candidate


def previous_b3_trading_day(day: date) -> date:
    """Retorna o último pregão estritamente anterior a ``day``."""
    candidate = day - timedelta(days=1)
    while not is_b3_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


def is_first_b3_trading_day_of_week(day: date) -> bool:
    """Informa se é o primeiro pregão da semana iniciada na segunda-feira."""
    monday = day - timedelta(days=day.weekday())
    return day == next_b3_trading_day(monday - timedelta(days=1))
