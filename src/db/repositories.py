"""
QuantB3 — Repositórios (CRUD) para todas as tabelas
"""

from __future__ import annotations

import logging
import json
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


def replace_pending_orders_for_signal_date(
    signal_date: date, orders: List[Dict[str, Any]]
) -> List[int]:
    """Substitui somente ordens ainda pendentes de uma geração de sinais.

    Ordens executadas ou canceladas são histórico imutável e nunca são tocadas.
    """
    with get_cursor() as cur:
        cur.execute(
            "DELETE FROM orders WHERE signal_date = %s AND status = 'PENDING'",
            (signal_date,),
        )
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
        for order in orders:
            cur.execute(sql, order)
            row = cur.fetchone()
            if row:
                ids.append(row["id"])
        return ids


def has_filled_orders_for_signal_date(signal_date: date) -> bool:
    """Indica se a geração já virou execução e, portanto, não pode ser refeita."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM orders WHERE signal_date = %s AND status = 'FILLED') AS exists",
            (signal_date,),
        )
        row = cur.fetchone()
        return bool(row and row["exists"])


def replace_weekly_plan(
    signal_date: date, signals: List[Dict[str, Any]], orders: List[Dict[str, Any]]
) -> List[int]:
    """Grava sinais e ordens pendentes como uma única operação atômica.

    Uma execução repetida antes da terça substitui o plano inteiro; depois de
    qualquer execução FILLED ela falha para manter o histórico coerente.
    """
    with get_cursor() as cur:
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM orders WHERE signal_date = %s AND status = 'FILLED') AS exists",
            (signal_date,),
        )
        if cur.fetchone()["exists"]:
            raise ValueError(
                f"Sinais de {signal_date} já possuem ordens executadas; geração bloqueada."
            )

        cur.execute("DELETE FROM signals WHERE signal_date = %s", (signal_date,))
        cur.execute(
            "DELETE FROM orders WHERE signal_date = %s AND status = 'PENDING'",
            (signal_date,),
        )

        if signals:
            cur.executemany(
                """
                INSERT INTO signals (signal_date, ticker, score, rank, action,
                                     target_qty, ref_price, stop_price, take_price)
                VALUES (%(signal_date)s, %(ticker)s, %(score)s, %(rank)s, %(action)s,
                        %(target_qty)s, %(ref_price)s, %(stop_price)s, %(take_price)s)
                """,
                signals,
            )

        order_ids = []
        if orders:
            order_sql = """
                INSERT INTO orders (signal_date, exec_date, ticker, side, qty,
                                    price, cost, status, note_id)
                VALUES (%(signal_date)s, %(exec_date)s, %(ticker)s, %(side)s, %(qty)s,
                        %(price)s, %(cost)s, %(status)s, %(note_id)s)
                RETURNING id
            """
            for order in orders:
                cur.execute(order_sql, order)
                row = cur.fetchone()
                if row:
                    order_ids.append(row["id"])
        return order_ids


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


def fill_order(order_id: int, price: float, cost: float, exec_date: date, qty: int) -> None:
    """Marca uma ordem como FILLED com preço de execução."""
    with get_cursor() as cur:
        cur.execute(
            """UPDATE orders SET status = 'FILLED', price = %s, cost = %s,
               exec_date = %s, qty = %s WHERE id = %s""",
            (price, cost, exec_date, qty, order_id)
        )


def cancel_order(order_id: int, reason: str) -> None:
    """Encerra uma ordem não executada, preservando o motivo no histórico."""
    with get_cursor() as cur:
        cur.execute(
            "UPDATE orders SET status = 'CANCELLED', note_id = %s WHERE id = %s",
            (reason[:500], order_id),
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


def replace_positions_snapshot(positions: List[Dict[str, Any]], as_of: date) -> int:
    """Substitui integralmente a fotografia de posições de uma data.

    Isso evita que um ticker encerrado sobreviva por engano em um snapshot novo.
    O marcador de quantidade zero mantém a data do snapshot mesmo sem posições.
    """
    with get_cursor() as cur:
        cur.execute("DELETE FROM positions WHERE as_of = %s", (as_of,))
        rows = [
            {**pos, "as_of": as_of}
            for pos in positions
            if int(pos.get("qty") or 0) > 0
        ]
        if not rows:
            rows = [{
                "as_of": as_of, "ticker": "__CASH__", "qty": 0,
                "avg_price": 0.0, "stop_price": None, "take_price": None,
            }]

        sql = """
            INSERT INTO positions (as_of, ticker, qty, avg_price, stop_price, take_price)
            VALUES (%(as_of)s, %(ticker)s, %(qty)s, %(avg_price)s, %(stop_price)s, %(take_price)s)
        """
        cur.executemany(sql, rows)
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
# DIÁRIO OPERACIONAL
# =============================================================================

def add_journal_entry(entry_date: date, ticker: Optional[str], category: str, note: str) -> None:
    """Salva uma anotação de decisão sem alterar ordens ou sinais."""
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO journal_entries (entry_date, ticker, category, note)
            VALUES (%s, %s, %s, %s)
            """,
            (entry_date, ticker.strip().upper() if ticker else None, category, note.strip()),
        )


def get_journal_entries(limit: int = 100) -> List[Dict[str, Any]]:
    """Retorna as anotações mais recentes do diário."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM journal_entries
            ORDER BY entry_date DESC, created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


# =============================================================================
# IBRX MODEL WATCH — EVENTOS E REGIMES
# =============================================================================

def add_market_event(
    *,
    ticker: Optional[str],
    event_type: str,
    event_class: str,
    published_at: date,
    effective_date: Optional[date],
    valid_from: Optional[date],
    valid_to: Optional[date],
    source_name: str,
    source_url: Optional[str],
    source_reference: Optional[str],
    summary: Optional[str],
) -> int:
    """Registra um alerta estruturado para validação humana posterior.

    A interface não pode criar eventos confirmados. Isso impede que um alerta
    não verificado entre silenciosamente no treinamento ou em sinais futuros.
    """
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO market_events (
                ticker, event_type, event_class, published_at, effective_date,
                valid_from, valid_to, source_name, source_url, source_reference,
                summary, status, confirmed
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                'PENDING_VALIDATION', false
            )
            RETURNING id
            """,
            (
                ticker.strip().upper() if ticker else None,
                event_type.strip().upper(),
                event_class.strip().upper(),
                published_at, effective_date, valid_from, valid_to,
                source_name.strip(), source_url.strip() if source_url else None,
                source_reference.strip() if source_reference else None,
                summary.strip() if summary else None,
            ),
        )
        row = cur.fetchone()
        return int(row["id"])


def get_market_events(limit: int = 250) -> List[Dict[str, Any]]:
    """Retorna alertas do Watch, inclusive os pendentes de validação."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM market_events
            ORDER BY published_at DESC, created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_confirmed_market_events(as_of_date: Optional[date] = None) -> pd.DataFrame:
    """Eventos confirmados e já públicos até ``as_of_date``.

    O filtro de divulgação é uma defesa complementar contra look-ahead; a
    engenharia de features repete a mesma garantia por linha temporal.
    """
    conditions = ["status = 'CONFIRMED'", "confirmed = true"]
    params: List[Any] = []
    if as_of_date is not None:
        conditions.append("published_at <= %s")
        params.append(as_of_date)
    where = " AND ".join(conditions)
    with get_cursor() as cur:
        cur.execute(
            f"SELECT * FROM market_events WHERE {where} ORDER BY published_at, id",
            params,
        )
        rows = [dict(row) for row in cur.fetchall()]
    return pd.DataFrame(rows)


def set_market_event_validation(
    event_id: int,
    *,
    approved: bool,
    validated_by: str,
    note: Optional[str] = None,
) -> None:
    """Registra a decisão de validação após conferência em fonte confiável.

    Esta operação é deliberadamente separada da ingestão. Quem cadastra um
    alerta não o promove a feature de produção sem uma confirmação explícita.
    """
    if not validated_by.strip():
        raise ValueError("Informe quem validou o evento")
    status = "CONFIRMED" if approved else "REJECTED"
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE market_events
            SET status = %s,
                confirmed = %s,
                confirmed_by = %s,
                confirmed_at = CASE WHEN %s THEN now() ELSE NULL END,
                confirmation_note = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (status, approved, validated_by.strip(), approved, note.strip() if note else None, event_id),
        )
        if cur.rowcount != 1:
            raise ValueError(f"Evento {event_id} não encontrado")


def upsert_market_event_staging(records: List[Dict[str, Any]]) -> int:
    """Persiste a fonte bruta do Watch sem promovê-la a feature do modelo."""
    if not records:
        return 0
    rows = []
    for record in records:
        rows.append({
            "source_event_id": record["event_id"],
            "event_type": record["event_type"],
            "ticker": record.get("ticker") or None,
            "alert_date": record.get("alert_date") or None,
            "official_disclosure_date": record.get("official_disclosure_date") or None,
            "effective_from": record.get("effective_from") or None,
            "effective_to": record.get("effective_to") or None,
            "validation_status": record["validation_status"],
            "oos_enabled": record["oos_enabled"],
            "source_confirmed": record["confirmed"],
            "official_source_url": record.get("official_source_url") or None,
            "secondary_source_url": record.get("secondary_source_url") or None,
            "source_message_id": record.get("source_message_id") or None,
            "event_stage": record.get("event_stage") or None,
            "validated_as_of": record.get("validated_as_of") or None,
            "notes": record.get("notes") or None,
            "raw_payload": json.dumps(record, ensure_ascii=False),
        })
    with get_cursor() as cur:
        cur.executemany(
            """
            INSERT INTO market_event_staging (
                source_event_id, event_type, ticker, alert_date,
                official_disclosure_date, effective_from, effective_to,
                validation_status, oos_enabled, source_confirmed,
                official_source_url, secondary_source_url, source_message_id,
                event_stage, validated_as_of, notes, raw_payload
            ) VALUES (
                %(source_event_id)s, %(event_type)s, %(ticker)s, %(alert_date)s,
                %(official_disclosure_date)s, %(effective_from)s, %(effective_to)s,
                %(validation_status)s, %(oos_enabled)s, %(source_confirmed)s,
                %(official_source_url)s, %(secondary_source_url)s, %(source_message_id)s,
                %(event_stage)s, %(validated_as_of)s, %(notes)s, %(raw_payload)s::jsonb
            ) ON CONFLICT (source_event_id) DO UPDATE SET
                event_type = EXCLUDED.event_type,
                ticker = EXCLUDED.ticker,
                alert_date = EXCLUDED.alert_date,
                official_disclosure_date = EXCLUDED.official_disclosure_date,
                effective_from = EXCLUDED.effective_from,
                effective_to = EXCLUDED.effective_to,
                validation_status = EXCLUDED.validation_status,
                oos_enabled = EXCLUDED.oos_enabled,
                source_confirmed = EXCLUDED.source_confirmed,
                official_source_url = EXCLUDED.official_source_url,
                secondary_source_url = EXCLUDED.secondary_source_url,
                source_message_id = EXCLUDED.source_message_id,
                event_stage = EXCLUDED.event_stage,
                validated_as_of = EXCLUDED.validated_as_of,
                notes = EXCLUDED.notes,
                raw_payload = EXCLUDED.raw_payload,
                updated_at = now()
            """,
            rows,
        )
    return len(rows)


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
