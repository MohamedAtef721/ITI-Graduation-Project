"""utils/database.py"""
import urllib.parse
import pandas as pd
from sqlalchemy import create_engine, text, inspect

_engine = None

def get_engine():
    return _engine

def connect(cfg):
    global _engine
    parts = [
        f"DRIVER={{{cfg.db_driver}}}",
        f"SERVER={cfg.db_server}",
        f"DATABASE={cfg.db_name}",
    ]
    if cfg.db_trusted:
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={cfg.db_username}")
        parts.append(f"PWD={cfg.db_password}")
    odbc = ";".join(parts) + ";"
    url  = f"mssql+pyodbc:///?odbc_connect={urllib.parse.quote_plus(odbc)}"
    _engine = create_engine(url, pool_pre_ping=True)
    with _engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return _engine

def run_query(sql: str, max_rows: int = 2000) -> list:
    """Execute SQL and return list of dicts (JSON-serializable)."""
    if _engine is None:
        return []
    with _engine.connect() as conn:
        result = conn.execute(text(sql))
        cols   = list(result.keys())
        rows   = result.fetchmany(max_rows)
    return [dict(zip(cols, r)) for r in rows]

def get_schema() -> dict:
    if _engine is None:
        return {}
    schema = {}
    inspector = inspect(_engine)
    for table in inspector.get_table_names(schema="dbo"):
        cols = inspector.get_columns(table, schema="dbo")
        schema[table] = [{"name": c["name"], "type": str(c["type"])} for c in cols]
    return schema
