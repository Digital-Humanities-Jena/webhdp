import multiprocessing
from flask import Flask
import pytest

from database.database import db
from services.registry_lock import registry_lock, OperationConflict


def test_registry_lock_excludes_other_processes_and_releases(tmp_path):
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{tmp_path}/registry.db'
    db.init_app(app)
    context = multiprocessing.get_context('fork')
    queue = context.Queue()

    def contender():
        with app.app_context():
            try:
                with registry_lock('versions'):
                    queue.put('acquired')
            except OperationConflict:
                queue.put('conflict')

    with app.app_context():
        with registry_lock('versions'):
            with registry_lock('versions'):
                process = context.Process(target=contender)
                process.start()
                process.join(5)
                assert not process.is_alive()
                assert queue.get(timeout=2) == 'conflict'
        process = context.Process(target=contender)
        process.start()
        process.join(5)
        assert queue.get(timeout=2) == 'acquired'
        with pytest.raises(RuntimeError):
            with registry_lock('versions'):
                raise RuntimeError('rollback')
        with registry_lock('versions'):
            pass
