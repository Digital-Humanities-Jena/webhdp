import pandas as pd

from routes.lod_mapping_helpers import build_pipeline_aligned_lod_metadata, spreadsheet_samples
from services.msf_service import MSFService


def test_build_pipeline_aligned_lod_metadata_uses_zenodo_defaults_for_missing_msf_fields():
    service = MSFService()
    row = pd.Series(
        {
            "filename": "6Kr_2.glb",
            "title": float("nan"),
            "creator": float("nan"),
            "date": float("nan"),
        }
    )
    mapping_config = {
        "dc:title": {"source": "msf", "field": "title"},
        "dc:creator": {"source": "msf", "field": "creator"},
        "dcterms:created": {"source": "msf", "field": "date"},
    }

    metadata = build_pipeline_aligned_lod_metadata(
        msf_service=service,
        row=row,
        zenodo_record={"metadata": {}},
        mapping_config=mapping_config,
        msf_profile={"filename_column": "filename"},
    )

    assert metadata["title"] == "6Kr_2"
    assert metadata["creators"] == [{"name": "Unknown"}]
    assert "cho_created" not in metadata
    assert isinstance(metadata["publication_date"], str)
    assert len(metadata["publication_date"]) == 10


def test_build_pipeline_aligned_lod_metadata_does_not_overwrite_with_empty_static_value():
    service = MSFService()
    row = pd.Series({"filename": "object.glb"})
    mapping_config = {
        "dc:title": {"source": "static", "value": ""},
    }

    metadata = build_pipeline_aligned_lod_metadata(
        msf_service=service,
        row=row,
        zenodo_record={"metadata": {"title": "Base title"}},
        mapping_config=mapping_config,
        msf_profile={"filename_column": "filename"},
    )

    assert metadata["title"] == "Base title"


def test_preview_applies_zenodo_mapping_before_lod_mapping_and_preserves_provider():
    metadata = build_pipeline_aligned_lod_metadata(
        msf_service=MSFService(),
        row=pd.Series({'filename': 'folder/object.glb', 'object_title': 'Mapped object'}),
        zenodo_record={'metadata': {'title': 'Shared title', 'edm_provider': 'Museum provider'}},
        zenodo_mapping={'title': {'source': 'msf', 'field': 'object_title'}},
        mapping_config={'dc:title': {'source': 'zenodo', 'field': 'title'}},
        msf_profile={'filename_column': 'filename'},
    )
    assert metadata['title'] == 'Mapped object'
    assert metadata['edm_provider'] == 'Museum provider'


def test_session_preview_uses_exact_batch_record_and_pipeline_fallbacks(tmp_path):
    import json
    import pytest
    from flask import Flask
    from database.database import db
    from database.models import User, Session, BatchFileMetadata
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    with app.app_context():
        db.create_all()
        user = User(email='preview@example.org')
        user.set_password('test-password')
        db.session.add(user)
        db.session.flush()
        session = Session(user_id=user.id, session_dir=str(tmp_path))
        db.session.add(session)
        db.session.flush()
        for filename, title in [('left/model.glb', 'Left object'), ('right/model.glb', 'Right object')]:
            db.session.add(BatchFileMetadata(session_id=session.id, filename=filename,
                                            metadata_json=json.dumps({'title': title, 'creators': [{'name': title + ' creator'}]})))
        db.session.commit()
        def preview(filename):
            return build_pipeline_aligned_lod_metadata(
                msf_service=MSFService(), row=pd.Series({'filename': filename}),
                zenodo_record={'metadata': {'title': 'Collection title', 'description': 'Collection description',
                                           'creators': [{'name': 'Default museum'}], 'edm_provider': 'Museum provider'}},
                mapping_config={'dc:title': {'source': 'zenodo', 'field': 'title'}},
                msf_profile={'filename_column': 'filename'}, session_id=session.id,
            )
        assert preview('right/model.glb')['title'] == 'Right object'
        assert preview('left/model.glb')['title'] == 'Left object'
        assert preview('right/model.glb')['creators'] == [{'name': 'Right object creator'}]
        fallback = preview('unmapped.glb')
        assert fallback['title'] == 'unmapped'
        assert fallback['description'] == 'No item-specific description provided.'
        assert fallback['creators'] == [{'name': 'Default museum'}]
        assert fallback['edm_provider'] == 'Museum provider'
        with pytest.raises(ValueError, match='Ambiguous'):
            preview('model.glb')
        db.session.remove()
        db.drop_all()


def test_provenance_distinguishes_actual_mapping_from_missing_value_defaults():
    metadata, provenance = build_pipeline_aligned_lod_metadata(
        msf_service=MSFService(), row=pd.Series({'filename': '模型.glb', 'dc:title': 'Museum object'}),
        zenodo_record={'metadata': {'creators': [], 'license': 'cc-by-4.0'}},
        mapping_config={'dc:title': {'source': 'msf', 'field': 'dc:title'},
                        'dc:creator': {'source': 'zenodo', 'field': 'creators'},
                        'dc:description': {'source': 'static', 'value': 'A curated description'}},
        msf_profile={'filename_column': 'filename'}, with_provenance=True,
    )
    assert metadata['title'] == 'Museum object'
    assert provenance['title'] == {'source': 'mapped', 'field': 'dc:title'}
    assert provenance['description']['source'] == 'entered'
    assert provenance['creators']['source'] == 'default'
    assert provenance['license']['source'] == 'entered'


def test_spreadsheet_quality_covers_every_row_and_creator_column_aliases():
    df = pd.DataFrame([
        {'filename': '模型.glb', 'dc:title': 'One', 'dc:description': 'Details', 'dc:creator': 'Museum'},
        {'filename': 'nested/model.glb', 'dc:title': 'Two', 'dc:description': None, 'dc:creator': float('nan')},
        {'filename': '模型.glb', 'dc:title': ' ', 'dc:description': '', 'dc:creator': ''},
    ])
    data = spreadsheet_samples(df, {'filename_column': 'filename'}, MSFService())
    assert data['sample_records'][1]['label'] == 'nested/model.glb · row 2'
    assert data['quality_summary']['missing'] == {'filename': 0, 'title': 1, 'description': 2, 'creators': 2}
    assert data['quality_summary']['duplicate_source_count'] == 1
    assert data['quality_summary']['row_count'] == 3
