from contextlib import closing
import sqlite3

from scripts.check_account_continuity import main


def make_database(database, rows):
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("""CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, created_at TEXT,
                                                  role TEXT, is_verified BOOLEAN)""")
        connection.executemany("INSERT INTO users VALUES (?, ?, ?, ?, ?)", rows)


def test_account_check_accepts_new_accounts_and_email_verification(tmp_path, capsys):
    database = tmp_path / "persistent #1.db"
    snapshot = tmp_path / "accounts.json"
    make_database(database, [(1, "admin@example.test", "2026-11-17 10:30:00", "admin", True),
                             (2, "existing@example.test", "2026-11-17 11:30:00", "user", False)])
    args = ["--database", str(database), "--snapshot", str(snapshot)]
    assert main(["capture", *args]) == 0
    assert snapshot.stat().st_mode & 0o777 == 0o600
    assert "@example.test" not in snapshot.read_text()

    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE users SET is_verified=1 WHERE id=2")
        connection.execute("INSERT INTO users VALUES (3, 'new@example.test', '2026-11-19 09:00:00', 'user', 0)")
    assert main(["verify", *args]) == 0
    assert "all 2 pre-update accounts" in capsys.readouterr().out


def test_account_check_rejects_a_replacement_database_and_accounts_that_lost_access(tmp_path, capsys):
    database = tmp_path / "original.db"
    other = tmp_path / "replacement.db"
    snapshot = tmp_path / "accounts.json"
    admin = (1, "admin@example.test", "2026-11-17", "admin", True)
    user = (2, "existing@example.test", "2026-11-18", "user", True)
    make_database(database, [admin, user])
    assert main(["capture", "--database", str(database), "--snapshot", str(snapshot)]) == 0

    make_database(other, [admin, (2, "new@example.test", "2026-11-19", "user", True)])
    assert main(["verify", "--database", str(other), "--snapshot", str(snapshot)]) == 1
    assert "1 accounts missing" in capsys.readouterr().err

    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE users SET is_verified=0 WHERE id=2")
        connection.execute("UPDATE users SET role='user' WHERE id=1")
    assert main(["verify", "--database", str(database), "--snapshot", str(snapshot)]) == 1
    assert "2 with changed roles or lost verification" in capsys.readouterr().err


def test_account_check_never_creates_a_missing_database(tmp_path):
    database = tmp_path / "missing.db"
    snapshot = tmp_path / "accounts.json"
    assert main(["capture", "--database", str(database), "--snapshot", str(snapshot)]) == 1
    assert not database.exists()
    assert not snapshot.exists()
