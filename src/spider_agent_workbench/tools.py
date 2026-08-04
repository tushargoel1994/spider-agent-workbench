
import sqlite3
from pathlib import Path
from langchain.tools import tool
from spider_agent_workbench.paths import DATABASES_DIR
import spider_agent_workbench.schema as schema
from spider_agent_workbench.executor import execute_query
from spider_agent_workbench.utils import format_result_table
from spider_agent_workbench.guardrails.sql_guardrails import validate_sql

@tool
def list_tables(db_id: str, db_dir:Path = DATABASES_DIR) -> str:
    """Search available tables inside a database
    
    Args:
        db_id: name of the database
        db_dir: folder that contains database, defaultvalue: data/spider/database/
    
    Returns a comma separated list of tables available in the database
    """
    
    table_list = schema.get_table_list(db_id, db_dir)
    if len(table_list) == 0:
        return f'Error, No table present in the database'
    available_table_str = ",".join(table_list)
    return available_table_str


@tool
def describe_table(db_id:str, table_name:str, db_dir:Path = DATABASES_DIR) -> str:
    """Provide a create sql for a specific table in database, can be used to understand table structure, relations and constraints on columns

    Args:
        db_id: name of database
        table_name: name of table
        db_dir: folder that contains database, defaultvalue: data/spider/database/
    """
    if db_id and table_name and table_name != '':
        table_info = schema.get_table_info(db_id, table_name, db_dir)
        if table_info is None:
            available_table_list = schema.get_table_list(db_id, db_dir)
            available_table_str = ",".join(available_table_list)
            return f"Error: no such table '{table_name}'. Available tables: {available_table_str}"
        return table_info
    else:
        return 'database name or table name not present'


@tool
def sample_rows(db_id:str, table_name:str, num_rows: int = 5, db_dir:Path = DATABASES_DIR) -> str:
    """Provide upto 5 records present in a table, used to understand the current data format

    Args:
        db_id: name of database
        table_name: name of table
        num_row: Number of rows to be returned, default value = 5
        db_dir: folder that contains database, defaultvalue: data/spider/database/
    """
    query = f"select * from {table_name} limit {num_rows}"
    result = _run_query_impl(db_id, query, db_dir, max_rows=num_rows)
    return result


def _run_query_impl(db_id:str, query:str, db_dir: Path=DATABASES_DIR, timeout: float=5.0, max_rows:int = 50) -> str:
    if query is None or query == '':
        return 'Error: Query empty, please fill query'
    guardrail_result = validate_sql(db_id, query, db_dir)
    if not guardrail_result.ok:
        return guardrail_result.reason
    try:
        query_result = execute_query(db_id, query, db_dir, timeout, max_rows)
        if query_result:
            if query_result.headers is None:
                return "Query executed but returned no result set."
            if not query_result.rows:
                return "Query returned no rows."
            table = format_result_table(query_result.headers, query_result.rows)
            if query_result.truncated:
                table += f"\n(truncated to first {max_rows} rows)"
            return table
    except sqlite3.Error as e:
        return f"SQL Error: {e}"


@tool
def run_query(db_id:str, query:str, db_dir: Path=DATABASES_DIR, timeout: float=5.0, max_rows:int = 50) -> str:
    """Execute a query on the provided database with timeout and row limit, to be used whenever a customer query is required to be run

    Args:
        db_id: name of database
        query: query to be executed
        timeout: maximum time for query to run, default = 5.0 seconds
        max_rows: Number of rows to be returned, default = 50
        db_dir: folder that contains database, defaultvalue: data/spider/database/
    """
    return _run_query_impl(db_id, query, db_dir, timeout, max_rows)


@tool
def submit_final_sql(db_id: str, query: str, db_dir: Path = DATABASES_DIR) -> str:
    """Submit the final SQL as the agent's answer.

    Does not execute the query — the agent loop detects this tool call
    (by name) and stops. Still runs the guardrails so a hallucinated
    table/column doesn't get submitted as the final answer.

    Args:
        db_id: name of the database this query targets
        query: the final SQL to submit
        db_dir: folder that contains database, defaultvalue: data/spider/database/
    """
    guardrail_result = validate_sql(db_id, query, db_dir)
    if not guardrail_result.ok:
        return guardrail_result.reason
    return f"Final SQL recorded: {query.strip()}"