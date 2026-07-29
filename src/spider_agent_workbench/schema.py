
import sqlite3
from pathlib import Path
from contextlib import closing
from spider_agent_workbench.paths import DATABASES_DIR
from spider_agent_workbench.utils import format_result_table


def list_databases(db_dir: Path = DATABASES_DIR) -> list[str]:
    """List all databases available to query"""
    db_list =  sorted(db.name for db in db_dir.iterdir() if db_dir.is_dir() and (db / f"{db.name}.sqlite").exists())
    return db_list

def get_sqlite_path(db_id: str, db_dir: Path= DATABASES_DIR) -> Path:
    """Given a database, return path to the database directory"""
    sqlite_path = db_dir/ db_id / f"{db_id}.sqlite"
    if db_dir.is_dir() and sqlite_path.exists():
        return sqlite_path
    return None

def get_table_info(db_id:str, table_name:str, db_dir: Path=DATABASES_DIR) -> str:
    sqlite_path = get_sqlite_path(db_id, db_dir)
    if sqlite_path is None:
        return None
    try:
        with closing(sqlite3.connect(sqlite_path)) as conn:
            row = conn.execute(f"select sql from sqlite_master where type='table' and name='{table_name}'").fetchone()
            if row is None:
                return None
            return row[0]
    except sqlite3.Error as e:
        return None



def get_table_list(db_id: str, db_dir: Path=DATABASES_DIR) -> list[str]:
    """Get list of all table names"""
    table_list_query = "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name"
    sqlite_path = get_sqlite_path(db_id, db_dir)
    if sqlite_path is None:
        return []
    try:
        with closing(sqlite3.connect(sqlite_path)) as conn:
            cursor = conn.execute(table_list_query).fetchall()
            tables = [row[0] for row in cursor] 
            return tables
    except sqlite3.Error as e:
        return [] 











