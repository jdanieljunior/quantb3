"""
QuantB3 — Gerador de Hash de Senha
====================================
Gera o hash SHA-256 da senha para configurar no dashboard.

Uso:
    python scripts/generate_password_hash.py
"""

import hashlib
import getpass


def main():
    print("QuantB3 — Gerador de Hash de Senha")
    print("=" * 40)
    print("Este hash será usado como DASHBOARD_PASSWORD_HASH")
    print()

    password = getpass.getpass("Digite a senha desejada: ")
    confirm = getpass.getpass("Confirme a senha: ")

    if password != confirm:
        print("Senhas não conferem!")
        return

    if len(password) < 8:
        print("Aviso: senha muito curta (mínimo recomendado: 8 caracteres)")

    hash_value = hashlib.sha256(password.encode()).hexdigest()

    print()
    print("Hash gerado:")
    print(f"  {hash_value}")
    print()
    print("Adicione ao .env:")
    print(f"  DASHBOARD_PASSWORD_HASH={hash_value}")
    print()
    print("Adicione ao Streamlit Secrets (secrets.toml):")
    print(f'  DASHBOARD_PASSWORD_HASH = "{hash_value}"')
    print()
    print("Adicione ao GitHub Secrets:")
    print(f"  Nome: DASHBOARD_PASSWORD_HASH")
    print(f"  Valor: {hash_value}")


if __name__ == "__main__":
    main()
