"""Create an isolated local PostgreSQL role/database without exposing passwords."""

import getpass
import os
import secrets
from pathlib import Path
from urllib.parse import quote

import psycopg
from psycopg import sql

ROLE = "merval_agent_test"
DATABASE = "merval_agent_test"
ENV_KEY = "TEST_DATABASE_URL"


def upsert_env(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replacement = f"{key}={value}"
    updated = []
    replaced = False
    for line in lines:
        if line.startswith(key + "="):
            updated.append(replacement)
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        if updated and updated[-1]:
            updated.append("")
        updated.append(replacement)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("\n".join(updated) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> None:
    admin_password = getpass.getpass(
        "Contraseña local del usuario postgres "
        "(no se mostrarán caracteres al escribir): "
    )
    app_password = secrets.token_urlsafe(24)
    connection_options = {
        "host": "127.0.0.1",
        "port": 5432,
        "dbname": "postgres",
        "user": "postgres",
        "password": admin_password,
        "connect_timeout": 5,
        "autocommit": True,
        "application_name": "merval-agent-local-bootstrap",
    }

    created_role = False
    try:
        with psycopg.connect(**connection_options) as db:
            role_exists = db.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (ROLE,)
            ).fetchone()
            database_exists = db.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (DATABASE,)
            ).fetchone()
            if role_exists or database_exists:
                raise RuntimeError(
                    "El rol o la base merval_agent_test ya existen. "
                    "No se modificaron credenciales existentes."
                )
            # PostgreSQL utility statements such as CREATE ROLE don't accept
            # extended-query parameters in this position. Compose both values
            # with psycopg's safe SQL objects instead of interpolating strings.
            db.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(ROLE), sql.Literal(app_password)
                )
            )
            created_role = True
            try:
                db.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(DATABASE), sql.Identifier(ROLE)
                    )
                )
            except Exception:
                db.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(ROLE)))
                raise
    finally:
        admin_password = ""

    if not created_role:
        raise RuntimeError("No se pudo crear el rol PostgreSQL de testing.")

    database_url = (
        "postgresql://"
        + quote(ROLE, safe="")
        + ":"
        + quote(app_password, safe="")
        + "@127.0.0.1:5432/"
        + quote(DATABASE, safe="")
    )
    upsert_env(Path(".env"), ENV_KEY, database_url)
    print("PostgreSQL local preparado y TEST_DATABASE_URL guardada en .env.")
    print(
        "Ejecutá: .\\.venv\\Scripts\\python.exe -m pytest -q -m live "
        "tests\\integration\\test_postgres_live.py"
    )


if __name__ == "__main__":
    main()
