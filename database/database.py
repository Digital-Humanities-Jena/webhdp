from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.engine.url import make_url

naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=naming_convention)


db = SQLAlchemy(model_class=Base)


def _is_file_backed_sqlite(database_uri: str) -> bool:
    try:
        url = make_url(database_uri)
    except Exception:
        return False
    if url.drivername not in {"sqlite", "sqlite+pysqlite"}:
        return False
    database = str(url.database or "")
    return bool(database and database != ":memory:")


def _is_sqlite(database_uri: str) -> bool:
    try:
        url = make_url(database_uri)
    except Exception:
        return False
    return url.drivername in {"sqlite", "sqlite+pysqlite"}


def _configure_sqlite_engine_options(app):
    database_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not _is_sqlite(database_uri):
        return

    engine_options = app.config.setdefault("SQLALCHEMY_ENGINE_OPTIONS", {})
    connect_args = engine_options.setdefault("connect_args", {})
    connect_args.setdefault("timeout", 30)
    connect_args.setdefault("check_same_thread", False)


def _register_sqlite_pragmas(app):
    database_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not _is_sqlite(database_uri):
        return

    use_wal = _is_file_backed_sqlite(database_uri)

    @event.listens_for(db.engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            if use_wal:
                cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()


def init_db(app):
    """Initialize database with Flask app"""
    _configure_sqlite_engine_options(app)
    db.init_app(app)
    with app.app_context():
        _register_sqlite_pragmas(app)
