import sys
from unittest.mock import MagicMock
import os

# Mock dependencies before importing EdmService
mock_db = MagicMock()
sys.modules['database.database'] = MagicMock(db=mock_db)
sys.modules['database.models'] = MagicMock()
sys.modules['flask_sqlalchemy'] = MagicMock()
sys.modules['flask_jwt_extended'] = MagicMock()

from flask import Flask
from services.edm_service import EdmService
from database.seed_edm_templates import (
    STANDARD_TEMPLATE, MODEL_3D_TEMPLATE, IMAGE_TEMPLATE,
    DOCUMENT_TEMPLATE, VIDEO_TEMPLATE, SOUND_TEMPLATE
)

def run_full_validation():
    app = Flask(__name__)
    # Set the real METIS URL if available in environment, otherwise use acceptance
    app.config['METIS_SANDBOX_URL'] = os.environ.get('METIS_SANDBOX_URL', 'https://metis-sandbox-rest.acceptance.eanadev.org')
    app.config['ENABLE_METIS_VALIDATION'] = True
    image_filename = "turin_1890.jpg"

    with app.app_context():
        edm_service = EdmService()
        # Mock mapping config
        edm_service._get_mapping_config = MagicMock(return_value={})

        # Scenarios to test
        scenarios = [
            {
                "name": "3D Mesh (Sketchfab oEmbed)",
                "template": MODEL_3D_TEMPLATE,
                "metadata": {
                    "title": "Turin Palace - 3D Mesh",
                    "language": "it",
                    "description": "A high-quality 3D mesh reconstruction of the Turin palace facade.",
                    "license": "CC-BY-4.0",
                    "edm_type_override": "3D",
                    "creators": [{"name": "Turin University"}],
                    "country": "IT"
                },
                "main_file": {
                    "viewer_url": "https://sketchfab.com/models/turin-facade/oembed",
                    "mime_type": "text/html",
                    "edm_type": "3D"
                }
            },
            {
                "name": "3D Point Cloud",
                "template": MODEL_3D_TEMPLATE,
                "metadata": {
                    "title": "Turin Palace - Point Cloud",
                    "language": "en",
                    "description": "Dense point cloud data from laser scanning.",
                    "license": "CC0-1.0",
                    "edm_type_override": "3D",
                    "point_count": 5000000,
                    "creators": [{"name": "Turin University"}],
                    "country": "IT"
                },
                "main_file": {
                    "viewer_url": "https://example.com/pointcloud/viewer",
                    "mime_type": "application/octet-stream",
                    "edm_type": "3D"
                }
            },
            {
                "name": "Heritage Image",
                "template": IMAGE_TEMPLATE,
                "metadata": {
                    "title": "Historical Photo of Turin",
                    "language": "mul",
                    "description": "Black and white photograph from the 19th century.",
                    "license": "Public Domain Mark",
                    "creators": [{"name": "Anonymous"}],
                    "publication_date": "1890-05-20",
                    "country": "IT"
                },
                "main_file": {
                    "viewer_url": "https://example.com/images/turin_1890.jpg",
                    "content_url": "https://example.com/images/turin_1890.jpg",
                    "mime_type": "image/jpeg",
                    "edm_type": "IMAGE",
                    "key": image_filename
                }
            },
            {
                "name": "Heritage Audio",
                "template": SOUND_TEMPLATE,
                "metadata": {
                    "title": "Oral History Interview",
                    "language": "it",
                    "description": "Interview regarding the reconstruction of the palace.",
                    "license": "CC-BY-NC-4.0",
                    "creators": [{"name": "Palace Archives"}],
                    "country": "IT"
                },
                "main_file": {
                    "viewer_url": "https://example.com/audio/interview.mp3",
                    "mime_type": "audio/mpeg",
                    "edm_type": "SOUND"
                }
            },
             {
                "name": "Heritage Video",
                "template": VIDEO_TEMPLATE,
                "metadata": {
                    "title": "Palace Restoration Documentary",
                    "language": "en",
                    "description": "Short film documenting the 2024 restoration project.",
                    "license": "CC-BY-4.0",
                    "creators": [{"name": "Modavis Media"}],
                    "country": "EU"
                },
                "main_file": {
                    "viewer_url": "https://example.com/video/doc.mp4",
                    "mime_type": "video/mp4",
                    "edm_type": "VIDEO"
                }
            },
            {
                "name": "Technical Report (Document)",
                "template": DOCUMENT_TEMPLATE,
                "metadata": {
                    "title": "Restoration Method Statement",
                    "language": "en",
                    "description": "Technical report on the materials used for the facade.",
                    "license": "CC-BY-4.0",
                    "creators": [{"name": "Ing. Mario Rossi"}],
                    "country": "IT"
                },
                "main_file": {
                    "viewer_url": "https://example.com/reports/statement.pdf",
                    "mime_type": "application/pdf",
                    "edm_type": "TEXT"
                }
            }
        ]

        zenodo_mock = {
            "id": "scenario_id",
            "links": {"html": "https://zenodo.org/records/scenario_id"},
            "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.scenario_id"}}
        }

        results = []

        print(f"Starting Live METIS Validation for {len(scenarios)} scenarios...")
        print(f"Target: {app.config['METIS_SANDBOX_URL']}")

        for scenario in scenarios:
            print(f"\nEvaluating: {scenario['name']}")

            # 1. Render XML
            helpers = edm_service._get_template_helpers()
            from jinja2 import Template
            template = Template(scenario['template'])
            normalized_meta = edm_service._normalize_edm_metadata_vocabularies(scenario['metadata'])

            xml_output = template.render(
                metadata=normalized_meta,
                zenodo=zenodo_mock,
                main_file=scenario['main_file'],
                helpers=helpers,
                thumbnail_file=None,
                additional_thumbnail_files=[]
            )

            # Ensure schema namespace
            xml_output = edm_service._ensure_schema_namespace(xml_output)

            # 2. Validate with METIS
            validation_result = edm_service.validate_with_metis(xml_output, metadata=normalized_meta)

            status_summary = "PASSED" if validation_result['valid'] else "FAILED"
            print(f"  Result: {status_summary} (Status: {validation_result.get('remote_status')})")

            if not validation_result['valid']:
                print("  Errors:")
                for err in validation_result.get('errors', []):
                    print(f"    - {err}")

            warnings = validation_result.get('warnings', [])
            if warnings:
                print("  Warnings/Problem Patterns:")
                for warn in warnings:
                    print(f"    - {warn}")

            results.append({
                "scenario": scenario['name'],
                "valid": validation_result['valid'],
                "errors": validation_result.get('errors', []),
                "warnings": warnings,
                "xml": xml_output
            })

        # Summary report
        print("\n" + "="*50)
        print("FINAL VALIDATION SUMMARY")
        print("="*50)
        passed_count = sum(1 for r in results if r['valid'])
        print(f"Passed: {passed_count}/{len(results)}")

        if passed_count < len(results):
            print("\nFailed Scenarios:")
            for r in results:
                if not r['valid']:
                    print(f"- {r['scenario']}")

        print("="*50)

if __name__ == "__main__":
    run_full_validation()
