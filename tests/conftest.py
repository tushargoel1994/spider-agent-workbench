"""Shared fixtures for the test suite.

Tests build their own throwaway sqlite database instead of relying on
data/spider/ (gitignored, not guaranteed to exist in a fresh checkout).
"""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

FIXTURE_DB_ID = "school"


@pytest.fixture()
def db_id() -> str:
    return FIXTURE_DB_ID


@pytest.fixture()
def db_dir(tmp_path: Path) -> Path:
    """A db_dir containing one fixture database with two related tables."""
    db_folder = tmp_path / FIXTURE_DB_ID
    db_folder.mkdir()
    sqlite_path = db_folder / f"{FIXTURE_DB_ID}.sqlite"
    with closing(sqlite3.connect(sqlite_path)) as conn:
        conn.executescript(
            """
            CREATE TABLE courses (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL
            );
            CREATE TABLE students (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                course_id INTEGER,
                FOREIGN KEY (course_id) REFERENCES courses(id)
            );
            INSERT INTO courses (id, title) VALUES (1, 'Math'), (2, 'History');
            INSERT INTO students (id, name, course_id) VALUES
                (1, 'Alice', 1),
                (2, 'Bob', 1),
                (3, 'Carol', 2);
            """
        )
        conn.commit()
    return tmp_path
