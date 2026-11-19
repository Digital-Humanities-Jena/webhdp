from concurrent.futures import ThreadPoolExecutor
from threading import Event

from flask import Flask
import pytest

from database.database import db
from database.models import ComponentDefinition, ComponentProfile, ComponentVersion, PipelineDefinition, PipelineRun, PipelineRunStatus, PipelineVersion, PlaygroundRun, User
from services.native_run_quota import NativeRunQuotaExceeded, admit_native_run, native_run_usage
from services.registry_lock import OperationConflict


@pytest.fixture
def registry(tmp_path):
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'runs.sqlite'}", NATIVE_PROCESSING_ACTIVE_LIMIT=1)
    db.init_app(app)
    with app.app_context():
        db.create_all()
        owner = User(email='owner@example.test', password_hash='fixture', is_verified=True)
        other = User(email='other@example.test', password_hash='fixture', is_verified=True)
        pipeline = PipelineDefinition(identifier='fixture', name='Fixture')
        component = ComponentDefinition(key='fixture', name='Fixture', source_type='native')
        db.session.add_all([owner, other, pipeline, component])
        db.session.flush()
        version = PipelineVersion(pipeline_definition_id=pipeline.id, version='1', config_json='{}', config_hash='fixture')
        component_version = ComponentVersion(component_definition_id=component.id, version='1', manifest_json='{}', manifest_hash='fixture')
        db.session.add_all([version, component_version])
        db.session.flush()
        profile = ComponentProfile(component_version_id=component_version.id, profile_id='local', adapter='local_cli', entrypoint_json='[]')
        db.session.add(profile)
        db.session.commit()
        return app, owner.id, other.id, (pipeline.id, version.id), (component_version.id, profile.id)


def reserve_pipeline(user_id, pipeline):
    with admit_native_run(user_id):
        run = PipelineRun(initiated_by_user_id=user_id, pipeline_definition_id=pipeline[0], pipeline_version_id=pipeline[1])
        db.session.add(run)
        db.session.commit()
        return run


def test_pipeline_and_playground_share_account_limit_and_release_it_when_done(registry):
    app, owner, other, pipeline, component = registry
    with app.app_context():
        run = reserve_pipeline(owner, pipeline)
        user = db.session.get(User, owner)
        assert native_run_usage(user) == {'queued': 1, 'running': 0, 'active': 1, 'active_limit': 1}
        with pytest.raises(NativeRunQuotaExceeded):
            with admit_native_run(owner):
                pytest.fail('A full account should have been rejected')

        with admit_native_run(other):
            db.session.add(PlaygroundRun(initiated_by_user_id=other, component_version_id=component[0],
                                        component_profile_id=component[1], status=PipelineRunStatus.RUNNING))
            db.session.commit()
        assert native_run_usage(db.session.get(User, other))['running'] == 1
        with pytest.raises(NativeRunQuotaExceeded):
            reserve_pipeline(other, pipeline)

        run.status = PipelineRunStatus.COMPLETED
        db.session.commit()
        assert native_run_usage(user)['active'] == 0
        reserve_pipeline(owner, pipeline)


def test_concurrent_admission_for_one_account_cannot_double_reserve(registry):
    app, owner, _, pipeline, _ = registry
    acquired = Event()
    release = Event()

    def reserve_first():
        with app.app_context(), admit_native_run(owner):
            acquired.set()
            assert release.wait(timeout=5)
            reserve_pipeline(owner, pipeline)

    with ThreadPoolExecutor() as pool:
        accepted = pool.submit(reserve_first)
        assert acquired.wait(timeout=5)
        try:
            with app.app_context(), pytest.raises(OperationConflict):
                reserve_pipeline(owner, pipeline)
        finally:
            release.set()
        accepted.result(timeout=5)

    with app.app_context(), pytest.raises(NativeRunQuotaExceeded):
        reserve_pipeline(owner, pipeline)
