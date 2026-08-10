"""
QuantB3 — Carga Inicial de Dados Históricos
============================================
Carrega o CSV histórico (cotacoes_ibrx_ohlcv_completo.csv) para o Supabase.

Uso:
    python scripts/load_initial_data.py [caminho_csv]

Execute UMA VEZ após configurar o banco de dados.
"""

import sys
import os
from pathlib import Path

# Adiciona o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    candidates = []
    if len(sys.argv) > 1:
        candidates.append(sys.argv[1])
    candidates += [
        "cotacoes_ibrx_ohlcv_completo.csv",
        "../cotacoes_ibrx_ohlcv_completo.csv",
        "data/cotacoes_ibrx_ohlcv_completo.csv",
    ]

    csv_path = None
    for p in candidates:
        if Path(p).exists():
            csv_path = p
            break

    if csv_path is None:
        print("CSV não encontrado. Passe o caminho como argumento:")
        print("  python scripts/load_initial_data.py /caminho/cotacoes_ibrx_ohlcv_completo.csv")
        sys.exit(1)

    logger.info(f"Carregando dados de: {csv_path}")

    # Testa conexão com banco
    from src.db.connection import test_connection
    if not test_connection():
        logger.error("Falha na conexão com o banco. Verifique DATABASE_URL no .env")
        sys.exit(1)

    # Carrega dados
    from src.data.collector import load_prices_from_csv
    df = load_prices_from_csv(csv_path)

    logger.info(f"Carga concluída: {len(df)} registros")
    logger.info("Próximo passo: execute o job de segunda-feira para gerar os primeiros sinais")


if __name__ == "__main__":
    main()
