"""
QuantB3 — Repositórios (CRUD) para todas as tabelas
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from src.db.connection import get_cursor

logger = logging.getLogger(__name__)


# =============================================================================
# PRICES
# =============================================================================

def upsert_prices(df: pd.DataFrame) -> int:
    """
    Insere/atualiza preços OHLCV no banco.
    df deve ter colunas: date, ticker, o, h, l, c, v
    """
    rows = df.to_dict("records")
    if not rows:
        return 0

    sql = """
        INSERT INTO prices (date, ticker, o, h, l, c, v)
        VALUES (%(date)s, %(ticker)s, %(o)s, %(h)s, %(l)s, %(c)s, %(v)s)
        ON CONFLICT (date, ticker) DO UPDATE SET
            o = EXCLUDED.o,
            h = EXCLUDED.h,
            l = EXCLUDED.l,
            c = EXCLUDED.c,
            v = EXCLUDED.v
    """
    with get_cursor() as cur:
        cur.executemany(sql, rows)
        return len(rows)


def get_prices(
    tickers: Optional[List[str]] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> pd.DataFrame:
    """Carrega preços do banco como DataFrame pivotado por Close."""
    conditions = []
    params: Dict[str, Any] = {}

    if tickers:
        conditions.append("ticker = ANY(%(tickers)s)")
        params["tickers"] = tickers
    if start_date:
        conditions.append("date >= %(start_date)s")
        params["start_date"] = start_date
    if end_date:
        conditions.append("date <= %(end_date)s")
        params["end_date"] = end_date

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"SELECT date, ticker, o, h, l, c, v FROM prices {where} ORDER BY date, ticker"

    with get_cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


def get_latest_price_date() -> Optional[date]:
    """Retorna a data mais recente com preços no banco."""
    with get_cursor() as cur:
        cur.execute("SELECT MAX(date) as max_date FROM prices")
        row = cur.fetchone()
        return row["max_date"] if row else None


def get_latest_price_dates(tickers: List[str]) -> Dict[str, date]:
    """Retorna a última cotação registrada para cada ticker informado."""
    if not tickers:
        return {}

    sql = """
        SELECT ticker, MAX(date) AS last_date
        FROM prices
        WHERE ticker = ANY(%(tickers)s)
        GROUP BY ticker
    """
    with get_cursor() as cur:
        cur.execute(sql, {"tickers": tickers})
        rows = cur.fetchall()

    return {row["ticker"]: row["last_date"] for row in rows if row["last_date"]}


# =============================================================================
# SIGNALS
# =============================================================================

def upsert_signals(signals: List[Dict[str, Any]]) -> int:
    """Insere/atualiza sinais gerados na segunda-feira."""
    if not signals:
        return 0

    sql = """
        INSERT INTO signals (signal_date, ticker, score, rank, action,
                             target_qty, ref_price, stop_price, take_price)
        VALUES (%(signal_date)s, %(ticker)s, %(score)s, %(rank)s, %(action)s,
                %(target_qty)s, %(ref_price)s, %(stop_price)s, %(take_price)s)
        ON CONFLICT (signal_date, ticker) DO UPDATE SET
            score = EXCLUDED.score,
            rank = EXCLUDED.rank,
            action = EXCLUDED.action,
            target_qty = EXCLUDED.target_qty,
            ref_price = EXCLUDED.ref_price,
            stop_price = EXCLUDED.stop_price,
            take_price = EXCLUDED.take_price
    """
    with get_cursor() as cur:
        cur.executemany(sql, signals)
        return len(signals)


def get_signals(signal_date: date) -> List[Dict[str, Any]]:
    """Retorna os sinais de uma data específica."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM signals WHERE signal_date = %s ORDER BY rank",
            (signal_date,)
        )
        return [dict(r) for r in cur.fetchall()]


def get_latest_signal_date() -> Optional[date]:
    """Retorna a data do último sinal gerado."""
    with get_cursor() as cur:
        cur.execute("SELECT MAX(signal_date) as max_date FROM signals")
        row = cur.fetchone()
        return row["max_date"] if row else None


# =============================================================================
# ORDERS
# =============================================================================

def insert_orders(orders: List[Dict[str, Any]]) -> List[int]:
    """Insere novas ordens com status PENDING."""
    if not orders:
        return []

    sql = """
        INSERT INTO orders (signal_date, exec_date, ticker, side, qty,
                            price, cost, status, note_id)
        VALUES (%(signal_date)s, %(exec_date)s, %(ticker)s, %(side)s, %(qty)s,
                %(price)s, %(cost)s, %(status)s, %(note_id)s)
        RETURNING id
    """
    ids = []
    with get_cursor() as cur:
        for order in orders:
            cur.execute(sql, order)
            row = cur.fetchone()
            if row:
                ids.append(row["id"])
    return ids


def get_pending_orders(signal_date: Optional[date] = None) -> List[Dict[str, Any]]:
    """Retorna ordens com status PENDING."""
    if signal_date:
        sql = "SELECT * FROM orders WHERE status = 'PENDING' AND signal_date = %s ORDER BY id"
        params = (signal_date,)
    else:
        sql = "SELECT * FROM orders WHERE status = 'PENDING' ORDER BY signal_date DESC, id"
        params = ()

    with get_cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def fill_order(order_id: int, price: float, cost: float, exec_date: date) -> None:
    """Marca uma ordem como FILLED com preço de execução."""
    with get_cursor() as cur:
        cur.execute(
            """UPDATE orders SET status = 'FILLED', price = %s, cost = %s,
               exec_date = %s WHERE id = %s""",
            (price, cost, exec_date, order_id)
        )


def get_orders(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retorna ordens com filtros opcionais."""
    conditions = []
    params: list = []

    if start_date:
        conditions.append("exec_date >= %s")
        params.append(start_date)
    if end_date:
        conditions.append("exec_date <= %s")
        params.append(end_date)
    if status:
        conditions.append("status = %s")
        params.append(status)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"SELECT * FROM orders {where} ORDER BY exec_date DESC, id"

    with get_cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


# =============================================================================
# POSITIONS
# =============================================================================

def upsert_positions(positions: List[Dict[str, Any]], as_of: date) -> int:
    """Insere/atualiza posições para uma data."""
    if not positions:
        return 0

    sql = """
        INSERT INTO positions (as_of, ticker, qty, avg_price, stop_price, take_price)
        VALUES (%(as_of)s, %(ticker)s, %(qty)s, %(avg_price)s, %(stop_price)s, %(take_price)s)
        ON CONFLICT (as_of, ticker) DO UPDATE SET
            qty = EXCLUDED.qty,
            avg_price = EXCLUDED.avg_price,
            stop_price = EXCLUDED.stop_price,
            take_price = EXCLUDED.take_price,
            updated_at = now()
    """
    for pos in positions:
        pos["as_of"] = as_of

    with get_cursor() as cur:
        cur.executemany(sql, positions)
        return len(positions)


def get_current_positions() -> List[Dict[str, Any]]:
    """Retorna as posições mais recentes."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT p.* FROM positions p
            WHERE p.as_of = (SELECT MAX(as_of) FROM positions)
            AND p.qty > 0
            ORDER BY p.ticker
        """)
        return [dict(r) for r in cur.fetchall()]


def get_positions_on_date(as_of: date) -> List[Dict[str, Any]]:
    """Retorna posições de uma data específica."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM positions WHERE as_of = %s AND qty > 0 ORDER BY ticker",
            (as_of,)
        )
        return [dict(r) for r in cur.fetchall()]


# =============================================================================
# EQUITY
# =============================================================================

def upsert_equity(
    date_val: date,
    equity: float,
    cash: float,
    pos_value: float,
    n_positions: int,
) -> None:
    """Insere/atualiza snapshot de equity."""
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO equity (date, equity, cash, pos_value, n_positions)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (date) DO UPDATE SET
                equity = EXCLUDED.equity,
                cash = EXCLUDED.cash,
                pos_value = EXCLUDED.pos_value,
                n_positions = EXCLUDED.n_positions
        """, (date_val, equity, cash, pos_value, n_positions))


def get_equity_curve(
    start_date: Optional[date] = None,
) -> pd.DataFrame:
    """Retorna a curva de equity como DataFrame."""
    if start_date:
        sql = "SELECT * FROM equity WHERE date >= %s ORDER BY date"
        params = (start_date,)
    else:
        sql = "SELECT * FROM equity ORDER BY date"
        params = ()

    with get_cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    if not rows:
        return pd.DataFrame(columns=["date", "equity", "cash", "pos_value", "n_positions"])

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


# =============================================================================
# NOTIFICATIONS
# =============================================================================

def log_notification(
    channel: str,
    kind: str,
    payload: str,
    status: str,
) -> None:
    """Registra uma notificação enviada."""
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO notifications (channel, kind, payload, status)
            VALUES (%s, %s, %s, %s)
        """, (channel, kind, payload, status))


def get_notifications(limit: int = 20) -> List[Dict[str, Any]]:
    """Retorna as últimas notificações."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM notifications ORDER BY sent_at DESC LIMIT %s",
            (limit,)
        )
        return [dict(r) for r in cur.fetchall()]


# =============================================================================
# EMAIL RECIPIENTS
# =============================================================================

def get_email_recipients(active_only: bool = False) -> List[Dict[str, Any]]:
    """Retorna destinatários configurados no dashboard."""
    where = "WHERE active = true" if active_only else ""
    with get_cursor() as cur:
        cur.execute(f"SELECT * FROM email_recipients {where} ORDER BY active DESC, email")
        return [dict(r) for r in cur.fetchall()]


def upsert_email_recipient(email: str, label: Optional[str] = None) -> None:
    """Inclui ou reativa um destinatário."""
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO email_recipients (email, label, active)
            VALUES (%s, %s, true)
            ON CONFLICT (email) DO UPDATE SET
                label = EXCLUDED.label, active = true, updated_at = now()
            """,
            (email.lower().strip(), label.strip() if label else None),
        )


def set_email_recipient_active(recipient_id: int, active: bool) -> None:
    """Ativa ou desativa um destinatário sem apagar histórico."""
    with get_cursor() as cur:
        cur.execute(
            "UPDATE email_recipients SET active = %s, updated_at = now() WHERE id = %s",
            (active, recipient_id),
        )


# =============================================================================
# RUNS (LOG DE JOBS)
# =============================================================================

def start_run(job: str) -> int:
    """Registra o início de um job e retorna o ID."""
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO runs (job, started_at, status)
            VALUES (%s, now(), 'running')
            RETURNING id
        """, (job,))
        row = cur.fetchone()
        return row["id"] if row else -1


def finish_run(run_id: int, status: str, log: str = "") -> None:
    """Registra o fim de um job."""
    with get_cursor() as cur:
        cur.execute("""
            UPDATE runs SET finished_at = now(), status = %s, log = %s
            WHERE id = %s
        """, (status, log, run_id))


def get_runs(limit: int = 20) -> List[Dict[str, Any]]:
    """Retorna os últimos runs."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT %s",
            (limit,)
        )
        return [dict(r) for r in cur.fetchall()]
