import hashlib
import logging

from database.database import db
from database.models import LodStandard, LodTemplate

logger = logging.getLogger(__name__)

IIIF_TEMPLATE_NAME = "IIIF Presentation 4.0 RC"
LEGACY_IIIF_TEMPLATE_NAMES = ("IIIF v3 3D Canvas", "IIIF v4 3D Scene")
LEGACY_IIIF_BUNDLE_HASHES = {"361fe2d578e7f01f497e70cf26663f40ee9545056fb8a676e02487faf34a17c1"}

# IiifService adds the appropriate container and resource after rendering.
IIIF_PRESENTATION_TEMPLATE = '''{
  "@context": {{ helpers.presentation_context | tojson }},
  "id": {{ helpers.manifest_id(metadata, zenodo) | tojson }},
  "type": "Manifest",
  "label": {{ helpers.lang_map(metadata.title | default('Untitled', true)) | tojson }},
  {% if metadata.description %}
  "summary": {{ helpers.lang_map(metadata.description) | tojson }},
  {% endif %}
  "items": []
}'''


def is_legacy_bundled_iiif_template(template):
    return (template.name in LEGACY_IIIF_TEMPLATE_NAMES
            and hashlib.sha256(template.content.encode("utf-8")).hexdigest() in LEGACY_IIIF_BUNDLE_HASHES)


def legacy_bundled_iiif_default():
    candidates = (LodTemplate.query.filter_by(standard=LodStandard.IIIF, is_default=True)
                  .filter(LodTemplate.name.in_(LEGACY_IIIF_TEMPLATE_NAMES)).order_by(LodTemplate.id).all())
    return next((template for template in candidates if is_legacy_bundled_iiif_template(template)), None)


def seed_iiif_templates():
    templates = LodTemplate.query.filter_by(standard=LodStandard.IIIF)
    template = templates.filter_by(name=IIIF_TEMPLATE_NAME).first()
    if template is None:
        template = legacy_bundled_iiif_default()
    if template is None:
        template = LodTemplate(standard=LodStandard.IIIF)
        db.session.add(template)

    template.name = IIIF_TEMPLATE_NAME
    template.description = "IIIF Presentation 4.0 release-candidate manifest for 3D, images, audio, video, and file links."
    template.format = "json"
    template.content = IIIF_PRESENTATION_TEMPLATE
    template.is_default = True
    db.session.commit()
    logger.info("Seeded %s template", IIIF_TEMPLATE_NAME)
