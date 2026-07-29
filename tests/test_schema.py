from spider_agent_workbench import schema

# Candidate tests for schema.py — uncomment/implement the ones you want.
#
# list_databases:
#   test_list_databases_finds_fixture_db          - returns the fixture db_id when its .sqlite file exists
#   test_list_databases_ignores_folder_without_sqlite - a subfolder with no matching .sqlite file is skipped
#   test_list_databases_empty_dir_returns_empty_list - db_dir with no subfolders returns []
#
# get_sqlite_path:
#   test_get_sqlite_path_existing_db               - returns a Path that exists for a known db_id
#   test_get_sqlite_path_missing_db_returns_none    - unknown db_id returns None instead of raising
#   test_get_sqlite_path_missing_db_dir_returns_none - nonexistent db_dir returns None
#
# get_table_info:
#   test_get_table_info_returns_create_statement   - known table returns its CREATE TABLE sql
#   test_get_table_info_unknown_table_returns_none - nonexistent table returns None (not raise)
#   test_get_table_info_unknown_db_returns_none    - nonexistent db_id returns None (sqlite3.Error caught)
#
# get_table_list:
#   test_get_table_list_returns_all_tables         - returns both fixture tables, sorted by name
#   test_get_table_list_excludes_sqlite_internal_tables - sqlite_% system tables never appear
#   test_get_table_list_unknown_db_returns_empty_list - nonexistent db_id returns [] rather than raising


def test_list_databases_finds_fixture_db(db_dir, db_id):
    assert schema.list_databases(db_dir) == [db_id]


def test_list_databases_ignores_folder_without_sqlite(db_dir, db_id):
    (db_dir / "not_a_db").mkdir()
    assert schema.list_databases(db_dir) == [db_id]


def test_list_databases_empty_dir_returns_empty_list(tmp_path):
    assert schema.list_databases(tmp_path) == []


def test_get_sqlite_path_existing_db(db_dir, db_id):
    path = schema.get_sqlite_path(db_id, db_dir)
    assert path is not None
    assert path.exists()


def test_get_sqlite_path_missing_db_returns_none(db_dir):
    assert schema.get_sqlite_path("missing_db", db_dir) is None


def test_get_sqlite_path_missing_db_dir_returns_none(tmp_path, db_id):
    assert schema.get_sqlite_path(db_id, tmp_path / "does_not_exist") is None


def test_get_table_info_returns_create_statement(db_dir, db_id):
    info = schema.get_table_info(db_id, "students", db_dir)
    assert info is not None
    assert "CREATE TABLE students" in info


def test_get_table_info_unknown_table_returns_none(db_dir, db_id):
    assert schema.get_table_info(db_id, "ghost", db_dir) is None


def test_get_table_info_unknown_db_returns_none(db_dir):
    assert schema.get_table_info("missing_db", "students", db_dir) is None


def test_get_table_list_returns_all_tables(db_dir, db_id):
    assert schema.get_table_list(db_id, db_dir) == ["courses", "students"]


def test_get_table_list_excludes_sqlite_internal_tables(db_dir, db_id):
    assert all(not t.startswith("sqlite_") for t in schema.get_table_list(db_id, db_dir))


def test_get_table_list_unknown_db_returns_empty_list(db_dir):
    assert schema.get_table_list("missing_db", db_dir) == []