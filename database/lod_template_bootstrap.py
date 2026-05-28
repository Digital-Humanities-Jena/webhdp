import logging

from database.database import db
from database.models import LodStandard, LodTemplate
from database.seed_edm_templates import seed_templates as seed_edm_templates
from database.seed_iiif_templates import seed_iiif_templates
from database.seed_mets_mods_templates import seed_mets_templates

logger = logging.getLogger(__name__)


def _current_standards() -> set[str]:
    standards: set[str] = set()
    for row in LodTemplate.query.with_entities(LodTemplate.standard).distinct().all():
        value = row[0]
        if isinstance(value, LodStandard):
            standards.add(value.value)
        elif value:
            standards.add(str(value).strip().lower())
    return standards


def _repair_edm_template_namespaces() -> int:
    updated = 0
    edm_templates = LodTemplate.query.filter_by(standard=LodStandard.EDM).all()
    for template in edm_templates:
        content = template.content or ""
        next_content = content
        if "svcs:" in next_content and 'xmlns:svcs="http://rdfs.org/sioc/services#"' not in next_content:
            next_content = next_content.replace(
                'xmlns:owl="http://www.w3.org/2002/07/owl#"',
                'xmlns:owl="http://www.w3.org/2002/07/owl#"\n'
                '         xmlns:svcs="http://rdfs.org/sioc/services#"',
                1,
            )
        if "rdfs:" in next_content and 'xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"' not in next_content:
            anchor = 'xmlns:svcs="http://rdfs.org/sioc/services#"'
            if anchor in next_content:
                next_content = next_content.replace(
                    anchor,
                    anchor + '\n         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"',
                    1,
                )
            else:
                next_content = next_content.replace(
                    'xmlns:owl="http://www.w3.org/2002/07/owl#"',
                    'xmlns:owl="http://www.w3.org/2002/07/owl#"\n'
                    '         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"',
                    1,
                )
        if next_content != content:
            template.content = next_content
            updated += 1
    if updated:
        logger.info("Patched %s EDM template(s) with missing namespace declarations", updated)
    return updated


def _repair_default_iiif_v3_template() -> int:
    """Upgrade the bundled IIIF template from the old v4 Scene draft to v3 Canvas."""
    updated = 0
    iiif_templates = LodTemplate.query.filter_by(standard=LodStandard.IIIF).all()
    for template in iiif_templates:
        content = template.content or ""
        if (
            "http://iiif.io/api/presentation/4/context.json" not in content
            and '"type": "Scene"' not in content
            and "IIIF v4 3D Scene" not in (template.name or "")
        ):
            continue
        if template.is_default or template.name == "IIIF v4 3D Scene":
            seed_iiif_templates()
            updated += 1
            break
    if updated:
        logger.info("Patched bundled IIIF template to Presentation v3 Canvas output")
    return updated


def ensure_default_lod_templates() -> dict[str, list[str]]:
    """Seed missing LOD template standards on demand."""
    existing = _current_standards()
    seeded: list[str] = []
    repaired: list[str] = []

    try:
        if LodStandard.EDM.value not in existing:
            seed_edm_templates()
            seeded.append(LodStandard.EDM.value)
        if LodStandard.IIIF.value not in existing:
            seed_iiif_templates()
            seeded.append(LodStandard.IIIF.value)
        if LodStandard.METS.value not in existing:
            seed_mets_templates()
            seeded.append(LodStandard.METS.value)
        if _repair_edm_template_namespaces():
            repaired.append(LodStandard.EDM.value)
        if _repair_default_iiif_v3_template():
            repaired.append(LodStandard.IIIF.value)
        if seeded or repaired:
            db.session.commit()
    except Exception:
        logger.exception("Failed to ensure default LOD templates are seeded")
        raise

    return {
        "seeded": seeded,
        "repaired": repaired,
        "available": sorted(_current_standards()),
    }
