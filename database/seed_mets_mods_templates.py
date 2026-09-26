# database/seed_mets_mods_templates.py
"""
Seed script for creating optimized METS/MODS templates.
Run this script to populate the database with best-practice METS templates.

Usage:
    flask shell
    >>> from database.seed_mets_mods_templates import seed_mets_templates
    >>> seed_mets_templates()
"""

from database.database import db
from database.models import LodTemplate, LodStandard
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# METS/MODS TEMPLATE (Standard)
# =============================================================================
METS_MODS_TEMPLATE = '''<?xml version="1.0" encoding="UTF-8"?>
<mets:mets xmlns:mets="http://www.loc.gov/METS/"
           xmlns:mods="http://www.loc.gov/mods/v3"
           xmlns:xlink="http://www.w3.org/1999/xlink"
           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
           xsi:schemaLocation="http://www.loc.gov/METS/ http://www.loc.gov/standards/mets/mets.xsd http://www.loc.gov/mods/v3 http://www.loc.gov/standards/mods/v3/mods-3-7.xsd"
           OBJID="hdp:{{ zenodo.id | default('unknown') }}"
           LABEL="{{ metadata.title }}"
           PROFILE="http://www.loc.gov/standards/mets/profiles/00000015.xml">

    <!-- METS Header -->
    <mets:metsHdr CREATEDATE="{{ helpers.iso_date_full(metadata.publication_date) if metadata.publication_date else helpers.now_iso() }}"
                  LASTMODDATE="{{ helpers.now_iso() }}"
                  RECORDSTATUS="Active">
        <mets:agent ROLE="CREATOR" TYPE="ORGANIZATION">
            <mets:name>{{ metadata.edm_provider | default('Heritage Data Processor') }}</mets:name>
        </mets:agent>
        {% for creator in metadata.creators %}
        <mets:agent ROLE="CREATOR" TYPE="INDIVIDUAL">
            <mets:name>{{ creator.name }}</mets:name>
            {% if creator.affiliation %}
            <mets:note>{{ creator.affiliation }}</mets:note>
            {% endif %}
        </mets:agent>
        {% endfor %}
    </mets:metsHdr>

    <!-- Descriptive Metadata (MODS) -->
    <mets:dmdSec ID="dmdSec_1">
        <mets:mdWrap MDTYPE="MODS">
            <mets:xmlData>
                <mods:mods>
                    <mods:titleInfo>
                        <mods:title>{{ metadata.title }}</mods:title>
                    </mods:titleInfo>

                    {% if metadata.description %}
                    <mods:note type="description">{{ metadata.description }}</mods:note>
                    {% endif %}

                    {% for creator in metadata.creators %}
                    <mods:name type="personal">
                        <mods:namePart>{{ creator.name }}</mods:namePart>
                        <mods:role>
                            <mods:roleTerm type="text">creator</mods:roleTerm>
                        </mods:role>
                        {% if creator.affiliation %}
                        <mods:affiliation>{{ creator.affiliation }}</mods:affiliation>
                        {% endif %}
                        {% if creator.orcid %}
                        <mods:nameIdentifier type="orcid">{{ creator.orcid }}</mods:nameIdentifier>
                        {% endif %}
                    </mods:name>
                    {% endfor %}

                    <mods:typeOfResource>{{ helpers.map_mods_type(main_file.content_type) }}</mods:typeOfResource>

                    <mods:originInfo>
                        {% if metadata.cho_created and metadata.cho_created|string|trim|lower not in ['unknown', 'n/a', 'na', 'none', 'undated'] %}
                        <mods:dateCreated>{{ helpers.iso_date(metadata.cho_created) }}</mods:dateCreated>
                        {% endif %}
                        {% if metadata.publication_date %}
                        <mods:dateIssued encoding="iso8601">{{ helpers.iso_date(metadata.publication_date) }}</mods:dateIssued>
                        {% endif %}
                        <mods:publisher>{{ metadata.provider | default('Zenodo') }}</mods:publisher>
                    </mods:originInfo>

                    <mods:identifier type="zenodo">{{ zenodo.id }}</mods:identifier>
                    {% if metadata._external_identifier %}
                    <mods:identifier type="local">{{ metadata._external_identifier }}</mods:identifier>
                    {% endif %}
                    {% if metadata.doi %}
                    <mods:identifier type="doi">{{ metadata.doi }}</mods:identifier>
                    {% elif zenodo.metadata.prereserve_doi.doi %}
                    <mods:identifier type="doi">{{ zenodo.metadata.prereserve_doi.doi }}</mods:identifier>
                    {% endif %}

                    {% if metadata.language %}
                    <mods:language>
                        <mods:languageTerm type="text">{{ metadata.language }}</mods:languageTerm>
                    </mods:language>
                    {% endif %}

                    {% if metadata.locations %}
                    {% for loc in metadata.locations %}
                    <mods:subject>
                        <mods:geographic>{{ loc.place }}</mods:geographic>
                        {% if loc.lat and loc.lon %}
                        <mods:cartographics>
                            <mods:coordinates>{{ loc.lat }}, {{ loc.lon }}</mods:coordinates>
                        </mods:cartographics>
                        {% endif %}
                    </mods:subject>
                    {% endfor %}
                    {% endif %}

                    {% if metadata.keywords %}
                    {% for keyword in metadata.keywords %}
                    <mods:subject>
                        <mods:topic>{{ keyword }}</mods:topic>
                    </mods:subject>
                    {% endfor %}
                    {% endif %}

                    <mods:accessCondition type="use and reproduction">{{ metadata.license }}</mods:accessCondition>
                </mods:mods>
            </mets:xmlData>
        </mets:mdWrap>
    </mets:dmdSec>

    <!-- File Section -->
    <mets:fileSec>
        <mets:fileGrp USE="ORIGINAL">
             {% if main_file %}
            <mets:file ID="{{ helpers.file_id(main_file.filename, 'FILE') }}" MIMETYPE="{{ main_file.mime_type }}"{% if main_file.size and main_file.size != 0 %} SIZE="{{ main_file.size }}"{% endif %}{% if main_file.checksum and main_file.checksum_type %} CHECKSUM="{{ main_file.checksum }}" CHECKSUMTYPE="{{ main_file.checksum_type }}"{% endif %}>
                <mets:FLocat LOCTYPE="URL" xlink:href="{{ main_file.content_url }}"/>
            </mets:file>
            {% endif %}
        </mets:fileGrp>
        {% if thumbnail_files and thumbnail_files|length > 0 %}
        <mets:fileGrp USE="THUMBNAIL">
            {% for thumb in thumbnail_files %}
            <mets:file ID="{{ helpers.file_id(thumb.filename, 'THUMB') }}" MIMETYPE="{{ thumb.mime_type }}"{% if thumb.size and thumb.size != 0 %} SIZE="{{ thumb.size }}"{% endif %}>
                <mets:FLocat LOCTYPE="URL" xlink:href="{{ thumb.content_url }}"/>
            </mets:file>
            {% endfor %}
        </mets:fileGrp>
        {% elif thumbnail_file %}
        <mets:fileGrp USE="THUMBNAIL">
            <mets:file ID="{{ helpers.file_id(thumbnail_file.filename, 'THUMB') }}" MIMETYPE="{{ thumbnail_file.mime_type }}"{% if thumbnail_file.size and thumbnail_file.size != 0 %} SIZE="{{ thumbnail_file.size }}"{% endif %}>
                <mets:FLocat LOCTYPE="URL" xlink:href="{{ thumbnail_file.content_url }}"/>
            </mets:file>
        </mets:fileGrp>
        {% endif %}
    </mets:fileSec>

    <!-- Structural Map -->
    <mets:structMap TYPE="LOGICAL">
        <mets:div TYPE="{{ helpers.map_structure_type(main_file.content_type) }}" DMDID="dmdSec_1" LABEL="{{ metadata.title }}">
            {% if main_file %}
            <mets:fptr FILEID="{{ helpers.file_id(main_file.filename, 'FILE') }}"/>
            {% endif %}
            {% if thumbnail_files and thumbnail_files|length > 0 %}
            <mets:div TYPE="THUMBNAIL">
                {% for thumb in thumbnail_files %}
                <mets:fptr FILEID="{{ helpers.file_id(thumb.filename, 'THUMB') }}"/>
                {% endfor %}
            </mets:div>
            {% elif thumbnail_file %}
            <mets:div TYPE="THUMBNAIL">
                <mets:fptr FILEID="{{ helpers.file_id(thumbnail_file.filename, 'THUMB') }}"/>
            </mets:div>
            {% endif %}
        </mets:div>
    </mets:structMap>

</mets:mets>'''


def seed_mets_templates():
    """Seeds the database with standard METS templates."""
    logger.info("Seeding METS templates...")

    templates = [
        {
            "name": "Standard METS/MODS v1.0",
            "description": "Standard METS container with embedded MODS metadata v3.7",
            "standard": LodStandard.METS,
            "format": "xml",
            "content": METS_MODS_TEMPLATE,
            "is_default": True
        }
    ]

    count = 0
    for tpl_data in templates:
        # Check if exists
        existing = LodTemplate.query.filter_by(name=tpl_data["name"], standard=LodStandard.METS).first()
        if existing:
            # Update content
            existing.content = tpl_data["content"]
            existing.description = tpl_data["description"]
            existing.is_default = tpl_data["is_default"]
            logger.info(f"Updated existing METS template: {existing.name}")
        else:
            # Create new
            new_tpl = LodTemplate(**tpl_data)
            db.session.add(new_tpl)
            logger.info(f"Created new METS template: {tpl_data['name']}")
            count += 1

    db.session.commit()
    logger.info(f"METS template seeding complete. Added {count} new templates.")
