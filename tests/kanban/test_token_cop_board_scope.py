"""Regression coverage for board-scoped Token Cop spawn counting."""
import importlib.util
import sqlite3
from pathlib import Path


TOKEN_COP = Path(r"C:\Users\mikey\AppData\Local\hermes\scripts\token_cop.py")


def load_token_cop():
    spec = importlib.util.spec_from_file_location("token_cop_regression", TOKEN_COP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_db(path: Path):
    c = sqlite3.connect(path)
    c.executescript(
        """
        CREATE TABLE tasks (id TEXT PRIMARY KEY, consecutive_failures INTEGER, status TEXT);
        CREATE TABLE task_events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, kind TEXT, created_at INTEGER);
        """
    )
    c.commit()
    c.close()


def test_spawn_count_is_board_scoped_and_reset_aware(tmp_path, monkeypatch):
    boards = tmp_path / "boards"
    tacticcal = boards / "tacticcal"
    probate = boards / "probate-firearm"
    tacticcal.mkdir(parents=True)
    probate.mkdir(parents=True)
    make_db(tacticcal / "kanban.db")
    make_db(probate / "kanban.db")

    c = sqlite3.connect(tacticcal / "kanban.db")
    c.execute("INSERT INTO tasks VALUES ('same-id', 0, 'running')")
    c.execute("INSERT INTO task_events(task_id,kind,created_at) VALUES ('same-id','reset',200)")
    c.execute("INSERT INTO task_events(task_id,kind,created_at) VALUES ('same-id','spawned',210)")
    c.commit()
    c.close()

    # Same task ID as an orphan on another board: these must not count.
    c = sqlite3.connect(probate / "kanban.db")
    c.executemany(
        "INSERT INTO task_events(task_id,kind,created_at) VALUES ('same-id','spawned',?)",
        [(150,), (160,), (170,)],
    )
    c.commit()
    c.close()

    tc = load_token_cop()
    monkeypatch.setattr(tc, "BOARDS_DIR", boards)
    assert tc.count_task_spawns("tacticcal", "same-id", 100) == 1
    assert tc.count_task_spawns("probate-firearm", "same-id", 100) == 0
