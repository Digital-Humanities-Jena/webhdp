# database/seed_iiif_templates.py
from database.database import db
from database.models import LodTemplate, LodStandard
import logging

logger = logging.getLogger(__name__)

IIIF_3D_SCENE_TEMPLATE = '''{
  "@context": "http://iiif.io/api/presentation/3/context.json",
  "id": "{{ metadata.iiif_manifest_id | default(zenodo.zenodo_url + '/manifest.json') }}",
  "type": "Manifest",
  "label": {{ helpers.lang_map(metadata.title | default('Untitled')) | tojson }},
  {% if metadata.description %}
  "summary": {{ helpers.lang_map(metadata.description) | tojson }},
  {% endif %}
  {% if thumbnail_files and thumbnail_files|length > 0 %}
  "thumbnail": [
    {% for thumb in thumbnail_files %}
    {
      "id": "{{ thumb.content_url }}",
      "type": "Image",
      "format": "{{ thumb.mime_type | default('image/jpeg') }}"
    }{% if not loop.last %},{% endif %}
    {% endfor %}
  ],
  {% elif thumbnail_file %}
  "thumbnail": [
    {
      "id": "{{ thumbnail_file.content_url }}",
      "type": "Image",
      "format": "{{ thumbnail_file.mime_type | default('image/jpeg') }}"
    }
  ],
  {% endif %}
  "items": [
    {
      "id": "{{ metadata.iiif_canvas_id | default(metadata.iiif_scene_id | default(zenodo.zenodo_url + '/canvas/1')) }}",
      "type": "Canvas",
      "label": {{ helpers.lang_map(metadata.iiif_canvas_label | default(metadata.iiif_scene_label | default('A Canvas'))) | tojson }},
      "items": [
        {
          "id": "{{ metadata.iiif_annotation_page_id | default(zenodo.zenodo_url + '/page/1') }}",
          "type": "AnnotationPage",
          "items": [
            {
              "id": "{{ metadata.iiif_annotation_id | default(zenodo.zenodo_url + '/annotation/1') }}",
              "type": "Annotation",
              "motivation": ["painting"],
              "body": [
                {% set has_transform = metadata.iiif_translate_x or metadata.iiif_translate_y or metadata.iiif_translate_z or metadata.iiif_rotate_x or metadata.iiif_rotate_y or metadata.iiif_rotate_z or (metadata.iiif_scale_x and metadata.iiif_scale_x != '1') or (metadata.iiif_scale_y and metadata.iiif_scale_y != '1') or (metadata.iiif_scale_z and metadata.iiif_scale_z != '1') %}
                {% if has_transform %}
                {
                  "type": "SpecificResource",
                  "source": {
                    "id": "{{ metadata.iiif_model_id | default(main_file.content_url) }}",
                    "type": "Model",
                    "format": "{{ metadata.iiif_model_format | default(main_file.format | default('model/gltf-binary')) }}"{% if metadata.iiif_model_label %},
                    "label": {{ helpers.lang_map(metadata.iiif_model_label) | tojson }}{% endif %}
                  },
                  "transform": [
                    {% if metadata.iiif_translate_x or metadata.iiif_translate_y or metadata.iiif_translate_z %}
                    {
                      "type": "TranslateTransform",
                      "x": {{ metadata.iiif_translate_x | default(0) | float }},
                      "y": {{ metadata.iiif_translate_y | default(0) | float }},
                      "z": {{ metadata.iiif_translate_z | default(0) | float }}
                    }{% if metadata.iiif_rotate_x or metadata.iiif_rotate_y or metadata.iiif_rotate_z or metadata.iiif_scale_x or metadata.iiif_scale_y or metadata.iiif_scale_z %},{% endif %}
                    {% endif %}
                    {% if metadata.iiif_rotate_x or metadata.iiif_rotate_y or metadata.iiif_rotate_z %}
                    {
                      "type": "RotateTransform",
                      "x": {{ metadata.iiif_rotate_x | default(0) | float }},
                      "y": {{ metadata.iiif_rotate_y | default(0) | float }},
                      "z": {{ metadata.iiif_rotate_z | default(0) | float }}
                    }{% if metadata.iiif_scale_x or metadata.iiif_scale_y or metadata.iiif_scale_z %},{% endif %}
                    {% endif %}
                    {% if metadata.iiif_scale_x or metadata.iiif_scale_y or metadata.iiif_scale_z %}
                    {
                      "type": "ScaleTransform",
                      "x": {{ metadata.iiif_scale_x | default(1) | float }},
                      "y": {{ metadata.iiif_scale_y | default(1) | float }},
                      "z": {{ metadata.iiif_scale_z | default(1) | float }}
                    }
                    {% endif %}
                  ]
                }
                {% else %}
                {
                  "id": "{{ metadata.iiif_model_id | default(main_file.content_url) }}",
                  "type": "Model",
                  "format": "{{ metadata.iiif_model_format | default(main_file.format | default('model/gltf-binary')) }}"{% if metadata.iiif_model_label %},
                  "label": {{ helpers.lang_map(metadata.iiif_model_label) | tojson }}{% endif %}
                }
                {% endif %}
              ],
              "target": [
                {% if metadata.iiif_point_x or metadata.iiif_point_y or metadata.iiif_point_z %}
                {
                  "type": "SpecificResource",
                  "source": {
                    "id": "{{ metadata.iiif_canvas_id | default(metadata.iiif_scene_id | default(zenodo.zenodo_url + '/canvas/1')) }}",
                    "type": "Canvas"
                  },
                  "selector": [
                    {
                      "type": "PointSelector",
                      "x": {{ metadata.iiif_point_x | default(0) | float }},
                      "y": {{ metadata.iiif_point_y | default(0) | float }},
                      "z": {{ metadata.iiif_point_z | default(0) | float }}
                    }
                  ]
                }
                {% else %}
                "{{ metadata.iiif_canvas_id | default(metadata.iiif_scene_id | default(zenodo.zenodo_url + '/canvas/1')) }}"
                {% endif %}
              ]
            }
          ]
        }
      ]
    }
  ]
}'''

def seed_iiif_templates():
    templates = [
        {
            "name": "IIIF v3 3D Canvas",
            "legacy_names": ["IIIF v4 3D Scene"],
            "description": "Standard IIIF Presentation v3 Manifest with a Canvas and 3D model annotation for GLB/FBX models.",
            "standard": LodStandard.IIIF,
            "format": "json",
            "content": IIIF_3D_SCENE_TEMPLATE,
            "is_default": True
        }
    ]

    for tpl_data in templates:
        template = LodTemplate.query.filter_by(name=tpl_data["name"]).first()
        if not template:
            for legacy_name in tpl_data.get("legacy_names", []):
                template = LodTemplate.query.filter_by(name=legacy_name).first()
                if template:
                    template.name = tpl_data["name"]
                    break
        if not template:
            template = LodTemplate(
                name=tpl_data["name"],
                description=tpl_data["description"],
                standard=tpl_data["standard"],
                format=tpl_data["format"],
                content=tpl_data["content"],
                is_default=tpl_data["is_default"]
            )
            db.session.add(template)
            logger.info(f"Added IIIF template: {tpl_data['name']}")
        else:
            template.content = tpl_data["content"]
            template.is_default = tpl_data["is_default"]
            logger.info(f"Updated IIIF template: {tpl_data['name']}")

    db.session.commit()
