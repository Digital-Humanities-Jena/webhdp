# database/seed_edm_templates.py
"""
Seed script for creating optimized EDM templates for various modalities.
Run this script to populate the database with best-practice EDM templates.

Usage:
    flask shell
    >>> from database.seed_edm_templates import seed_templates
    >>> seed_templates()
"""

from database.database import db
from database.models import LodTemplate, LodStandard
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# OPTIMIZED STANDARD TEMPLATE (Default)
# =============================================================================
STANDARD_TEMPLATE = '''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:edm="http://www.europeana.eu/schemas/edm/"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:ore="http://www.openarchives.org/ore/terms/"
         xmlns:skos="http://www.w3.org/2004/02/skos/core#"
         xmlns:foaf="http://xmlns.com/foaf/0.1/"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:svcs="http://rdfs.org/sioc/services#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
         xmlns:schema="https://schema.org/"
         xmlns:wgs84_pos="http://www.w3.org/2003/01/geo/wgs84_pos#">

  {% set cho_uri = "https://doi.org/" + metadata.doi if metadata.doi else ("https://doi.org/" + zenodo.metadata.get('prereserve_doi', {}).get('doi') if zenodo.metadata.get('prereserve_doi', {}).get('doi') else zenodo.links.html | replace('/deposit/', '/records/')) %}
  {% set aggregation_uri = cho_uri + "#aggregation" %}

  <edm:ProvidedCHO rdf:about="{{ cho_uri }}">
    <dc:title xml:lang="{{ metadata.language | default('en') }}">{{ metadata.title }}</dc:title>

    {% if metadata.description %}
    <dc:description xml:lang="{{ metadata.language | default('en') }}">{{ metadata.description }}</dc:description>
    {% endif %}

    {% for creator in metadata.creators %}
    <dc:creator rdf:resource="{{ helpers.generate_uri('agent', creator.name) }}"/>
    {% endfor %}

    {% if metadata.provider %}
    <dc:publisher>{{ metadata.provider }}</dc:publisher>
    {% endif %}

    {% if metadata.cho_created %}
    <dcterms:created>{{ helpers.iso_date(metadata.cho_created) }}</dcterms:created>
    {% endif %}

    {% if metadata._external_identifier %}
    <dc:identifier>{{ metadata._external_identifier }}</dc:identifier>
    {% endif %}
    <dc:identifier>{{ zenodo.metadata.prereserve_doi.doi }}</dc:identifier>
    <dc:identifier>{{ zenodo.id }}</dc:identifier>

    {% if metadata.keywords %}
    {% for keyword in metadata.keywords %}
    <dc:subject>{{ keyword }}</dc:subject>
    {% endfor %}
    {% endif %}

    {% if metadata.language %}
    <dc:language>{{ metadata.language }}</dc:language>
    {% endif %}

    <dc:type>{{ main_file.content_type | default('other') | capitalize }}</dc:type>
    {% if metadata.get('resource_type') %}
    <dc:type>{{ metadata.get('resource_type') }}</dc:type>
    {% endif %}

    {% if metadata.locations %}
    {% for loc in metadata.locations %}
    <dcterms:spatial rdf:resource="{{ helpers.generate_uri('place', loc.place + '_' + loop.index|string) }}"/>
    {% endfor %}
    {% endif %}

    <edm:type>{{ main_file.edm_type }}</edm:type>
    {% if metadata.doi %}
    <owl:sameAs rdf:resource="https://doi.org/{{ metadata.doi }}"/>
    {% endif %}
  </edm:ProvidedCHO>

  <!-- 2. WebResources -->

  <!-- Landing Page -->
  <edm:WebResource rdf:about="{{ zenodo.links.html | replace('/deposit/', '/records/') }}">
    <dc:format>text/html</dc:format>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </edm:WebResource>

  <!-- Digital Object (Main File) -->
  {% if main_file %}
  <edm:WebResource rdf:about="{{ main_file.content_url }}">
    <dc:format>{{ main_file.mime_type | default(main_file.format | default('application/octet-stream')) }}</dc:format>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
    {% set intended_usage_uri = helpers.normalize_intended_usage_uri(metadata.intended_usage) %}
    {% if intended_usage_uri %}
    <edm:intendedUsage rdf:resource="{{ helpers.normalize_intended_usage_uri(metadata.intended_usage) }}"/>
    {% endif %}
  </edm:WebResource>
  {% endif %}

  <!-- Thumbnail (if different from main file) -->
  {% if thumbnail_file and thumbnail_file.content_url != main_file.content_url %}
  <edm:WebResource rdf:about="{{ thumbnail_file.content_url }}">
    <dc:format>image/jpeg</dc:format>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </edm:WebResource>
  {% endif %}
  {% if additional_thumbnail_files %}
  {% for thumb in additional_thumbnail_files %}
  {% if thumb.content_url != main_file.content_url %}
  <edm:WebResource rdf:about="{{ thumb.content_url }}">
    <dc:format>image/jpeg</dc:format>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </edm:WebResource>
  {% endif %}
  {% endfor %}
  {% endif %}

  <!-- 3. Agents -->
  {% for creator in metadata.creators %}
  <edm:Agent rdf:about="{{ helpers.generate_uri('agent', creator.name) }}">
    <skos:prefLabel xml:lang="{{ metadata.language | default('en') }}">{{ creator.name }}</skos:prefLabel>
    {% if creator.affiliation %}
    <skos:note>{{ creator.affiliation }}</skos:note>
    {% endif %}
    {% if creator.orcid %}
    <owl:sameAs rdf:resource="https://orcid.org/{{ creator.orcid }}"/>
    {% endif %}
  </edm:Agent>
  {% endfor %}

  <!-- 4. Places -->
  {% if metadata.locations %}
  {% for loc in metadata.locations %}
  <edm:Place rdf:about="{{ helpers.generate_uri('place', loc.place + '_' + loop.index|string) }}">
    {% if loc.lat and loc.lon %}
    <wgs84_pos:lat>{{ loc.lat }}</wgs84_pos:lat>
    <wgs84_pos:long>{{ loc.lon }}</wgs84_pos:long>
    {% endif %}
    <skos:prefLabel xml:lang="{{ metadata.language | default('en') }}">{{ loc.place }}</skos:prefLabel>
    {% if loc.description %}
    <skos:note xml:lang="{{ metadata.language | default('en') }}">{{ loc.description }}</skos:note>
    {% endif %}
  </edm:Place>
  {% endfor %}
  {% endif %}

  <!-- 5. Aggregation -->
  <ore:Aggregation rdf:about="{{ aggregation_uri }}">
    <edm:aggregatedCHO rdf:resource="{{ cho_uri }}"/>
    <edm:dataProvider>{{ metadata.provider | default('Zenodo') }}</edm:dataProvider>
    <edm:isShownAt rdf:resource="{{ zenodo.links.html | replace('/deposit/', '/records/') }}"/>

    {% if main_file %}
    {% if main_file.viewer_url %}
    <edm:isShownBy rdf:resource="{{ main_file.viewer_url }}"/>
    {% endif %}
    <edm:hasView rdf:resource="{{ main_file.content_url }}"/>
    {% endif %}

    {% if thumbnail_files %}
    {% for thumb in thumbnail_files %}
    <edm:hasView rdf:resource="{{ thumb.content_url }}"/>
    {% endfor %}
    {% endif %}

    {% if thumbnail_file %}
    <edm:object rdf:resource="{{ thumbnail_file.content_url }}"/>
    {% endif %}

    <edm:provider>{{ metadata.edm_provider | default('Heritage Data Processor') }}</edm:provider>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </ore:Aggregation>

</rdf:RDF>'''


# =============================================================================
# 3D MODEL TEMPLATE (edm:type = 3D)
# =============================================================================
MODEL_3D_TEMPLATE = '''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:edm="http://www.europeana.eu/schemas/edm/"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:ore="http://www.openarchives.org/ore/terms/"
         xmlns:skos="http://www.w3.org/2004/02/skos/core#"
         xmlns:foaf="http://xmlns.com/foaf/0.1/"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:svcs="http://rdfs.org/sioc/services#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
         xmlns:schema="https://schema.org/"
         xmlns:wgs84_pos="http://www.w3.org/2003/01/geo/wgs84_pos#">

  {% set cho_uri = "https://doi.org/" + metadata.doi if metadata.doi else ("https://doi.org/" + zenodo.metadata.get('prereserve_doi', {}).get('doi') if zenodo.metadata.get('prereserve_doi', {}).get('doi') else zenodo.links.html | replace('/deposit/', '/records/')) %}
  {% set aggregation_uri = cho_uri + "#aggregation" %}

  <edm:ProvidedCHO rdf:about="{{ cho_uri }}">
    <dc:title xml:lang="{{ metadata.language | default('en') }}">{{ metadata.title }}</dc:title>

    {% if metadata.description %}
    <dc:description xml:lang="{{ metadata.language | default('en') }}">{{ metadata.description }}</dc:description>
    {% endif %}

    {% for creator in metadata.creators %}
    <dc:creator rdf:resource="{{ helpers.generate_uri('agent', creator.name) }}"/>
    {% endfor %}

    {% if metadata.cho_created %}
    <dcterms:created>{{ helpers.iso_date(metadata.cho_created) }}</dcterms:created>
    {% endif %}

    {% if metadata._external_identifier %}
    <dc:identifier>{{ metadata._external_identifier }}</dc:identifier>
    {% endif %}
    <dc:identifier>{{ zenodo.metadata.prereserve_doi.doi }}</dc:identifier>
    <dc:identifier>{{ zenodo.id }}</dc:identifier>

    <dc:type>3D model</dc:type>
    {% if metadata.get('resource_type') %}
    <dc:type>{{ metadata.get('resource_type') }}</dc:type>
    {% endif %}

    {% if metadata.keywords %}
    {% for keyword in metadata.keywords %}
    <dc:subject>{{ keyword }}</dc:subject>
    {% endfor %}
    {% endif %}

    {% if metadata.locations %}
    {% for loc in metadata.locations %}
    <dcterms:spatial rdf:resource="{{ helpers.generate_uri('place', loc.place + '_' + loop.index|string) }}"/>
    {% endfor %}
    {% endif %}

    {% if metadata.temporal %}
    <dcterms:temporal>{{ metadata.temporal }}</dcterms:temporal>
    {% endif %}

    {% if metadata.medium %}
    <dcterms:medium>{{ metadata.medium }}</dcterms:medium>
    {% endif %}

    <edm:type>3D</edm:type>
    {% if metadata.doi %}
    <owl:sameAs rdf:resource="https://doi.org/{{ metadata.doi }}"/>
    {% endif %}
  </edm:ProvidedCHO>

  <!-- 2. WebResources -->

  <!-- Landing Page -->
  <edm:WebResource rdf:about="{{ zenodo.links.html | replace('/deposit/', '/records/') }}">
     <dc:format>text/html</dc:format>
     <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </edm:WebResource>

  <!-- Digital Object (3D Model) -->
  {% if main_file %}
  <edm:WebResource rdf:about="{{ main_file.content_url }}">
    <dc:format>{{ main_file.mime_type | default('model/gltf-binary') }}</dc:format>
    {% if metadata.extent %}
    <dcterms:extent>{{ metadata.extent }}</dcterms:extent>
    {% endif %}

    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
    {% set digital_source_type_uri = helpers.normalize_digital_source_type_uri(metadata.digital_source_type) %}
    {% if digital_source_type_uri %}
    <schema:digitalSourceType rdf:resource="{{ digital_source_type_uri }}"/>
    {% endif %}
    {% set intended_usage_uri = helpers.normalize_intended_usage_uri(metadata.intended_usage) %}
    {% if intended_usage_uri %}
    <edm:intendedUsage rdf:resource="{{ intended_usage_uri }}"/>
    {% endif %}
    <edm:type>3D</edm:type>
    {% if metadata.vertex_count %}
    <edm:vertexCount>{{ metadata.vertex_count }}</edm:vertexCount>
    {% endif %}

    {% if metadata.polygon_count %}
    <edm:polygonCount>{{ metadata.polygon_count }}</edm:polygonCount>
    {% endif %}

    {% if metadata.point_count %}
    <edm:pointCount>{{ metadata.point_count }}</edm:pointCount>
    {% endif %}

    <dc:type rdf:resource="{{ helpers.map_3d_type(metadata) }}"/>
  </edm:WebResource>

  {% if helpers.is_oembed(main_file.viewer_url) %}
  <edm:WebResource rdf:about="{{ main_file.viewer_url }}">
    <dc:format>text/html</dc:format>
    <dcterms:isFormatOf rdf:resource="{{ main_file.content_url }}"/>
    <dcterms:conformsTo rdf:resource="https://oembed.com/"/>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
    <svcs:has_service rdf:resource="{{ main_file.viewer_url }}#Service"/>
  </edm:WebResource>
  {% endif %}

  {% if helpers.is_oembed(main_file.viewer_url) %}
  <svcs:Service rdf:about="{{ main_file.viewer_url }}#Service">
    <dcterms:conformsTo rdf:resource="https://oembed.com/"/>
    <rdfs:label>3D Viewer</rdfs:label>
  </svcs:Service>
  {% endif %}
  {% endif %}

  <!-- Thumbnail -->
  {% if thumbnail_file %}
  <edm:WebResource rdf:about="{{ thumbnail_file.content_url }}">
    <dc:format>image/jpeg</dc:format>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </edm:WebResource>
  {% endif %}
  {% if additional_thumbnail_files %}
  {% for thumb in additional_thumbnail_files %}
  <edm:WebResource rdf:about="{{ thumb.content_url }}">
    <dc:format>image/jpeg</dc:format>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </edm:WebResource>
  {% endfor %}
  {% endif %}

  <!-- 3. Agents -->
  {% for creator in metadata.creators %}
  <edm:Agent rdf:about="{{ helpers.generate_uri('agent', creator.name) }}">
    <skos:prefLabel xml:lang="{{ metadata.language | default('en') }}">{{ creator.name }}</skos:prefLabel>
    {% if creator.affiliation %}
    <skos:note>{{ creator.affiliation }}</skos:note>
    {% endif %}
    {% if creator.orcid %}
    <owl:sameAs rdf:resource="https://orcid.org/{{ creator.orcid }}"/>
    {% endif %}
  </edm:Agent>
  {% endfor %}

  <!-- 4. Places -->
  {% if metadata.locations %}
  {% for loc in metadata.locations %}
  <edm:Place rdf:about="{{ helpers.generate_uri('place', loc.place + '_' + loop.index|string) }}">
    {% if loc.lat and loc.lon %}
    <wgs84_pos:lat>{{ loc.lat }}</wgs84_pos:lat>
    <wgs84_pos:long>{{ loc.lon }}</wgs84_pos:long>
    {% endif %}
    <skos:prefLabel xml:lang="{{ metadata.language | default('en') }}">{{ loc.place }}</skos:prefLabel>
    {% if loc.description %}
    <skos:note xml:lang="{{ metadata.language | default('en') }}">{{ loc.description }}</skos:note>
    {% endif %}
  </edm:Place>
  {% endfor %}
  {% endif %}

  <!-- 5. Aggregation -->
  <ore:Aggregation rdf:about="{{ aggregation_uri }}">
    <edm:aggregatedCHO rdf:resource="{{ cho_uri }}"/>
    <edm:dataProvider>{{ metadata.provider | default('Zenodo') }}</edm:dataProvider>
    <edm:isShownAt rdf:resource="{{ zenodo.links.html | replace('/deposit/', '/records/') }}"/>

    {% if main_file %}
    <edm:hasView rdf:resource="{{ main_file.content_url }}"/>
    {% if helpers.is_oembed(main_file.viewer_url) %}
    <edm:isShownBy rdf:resource="{{ main_file.viewer_url }}"/>
    {% endif %}
    {% endif %}

    {% if thumbnail_files %}
    {% for thumb in thumbnail_files %}
    <edm:hasView rdf:resource="{{ thumb.content_url }}"/>
    {% endfor %}
    {% endif %}

    {% if thumbnail_file %}
    <edm:object rdf:resource="{{ thumbnail_file.content_url }}"/>
    {% endif %}

    <edm:provider>{{ metadata.edm_provider | default('Heritage Data Processor') }}</edm:provider>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </ore:Aggregation>

</rdf:RDF>'''

# =============================================================================
# IMAGE TEMPLATE (Photography, Artwork, Scans - edm:type = IMAGE)
# =============================================================================
IMAGE_TEMPLATE = '''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF
    xmlns:crm="http://www.cidoe-crm.org/rdfs/cidoc_crm_v5.0.2_english_label.rdfs#"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:dcterms="http://purl.org/dc/terms/"
    xmlns:edm="http://www.europeana.eu/schemas/edm/"
    xmlns:foaf="http://xmlns.com/foaf/0.1/"
    xmlns:ore="http://www.openarchives.org/ore/terms/"
    xmlns:owl="http://www.w3.org/2002/07/owl#"
    xmlns:rdaGr2="http://rdvocab.info/ElementsGr2/"
    xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
    xmlns:skos="http://www.w3.org/2004/02/skos/core#"
    xmlns:svcs="http://rdfs.org/sioc/services#"
    xmlns:wgs84_pos="http://www.w3.org/2003/01/geo/wgs84_pos#"
    xmlns:xalan="http://xml.apache.org/xalan">

  {% set cho_uri = "https://doi.org/" + metadata.doi if metadata.doi else ("https://doi.org/" + zenodo.metadata.get('prereserve_doi', {}).get('doi') if zenodo.metadata.get('prereserve_doi', {}).get('doi') else zenodo.links.html | replace('/deposit/', '/records/')) %}
  {% set aggregation_uri = cho_uri + "#aggregation" %}

  <edm:ProvidedCHO rdf:about="{{ cho_uri }}">
    <dc:title xml:lang="{{ metadata.language | default('en') }}">{{ metadata.title | default(main_file.key) }}</dc:title>

    {% if metadata.description %}
    <dc:description xml:lang="{{ metadata.language | default('en') }}">{{ metadata.description }}</dc:description>
    {% endif %}

    {% for creator in metadata.creators %}
    <dc:creator rdf:resource="{{ helpers.generate_uri('agent', creator.name) }}"/>
    {% endfor %}

    {% if metadata.format or True %}
    <dc:format xml:lang="en">{{ metadata.format | default('image/jpeg') }}</dc:format>
    {% endif %}

    <dc:identifier>{{ main_file.key }}</dc:identifier>
    <dc:language>{{ metadata.language | default('en') }}</dc:language>

    <dc:type>Image</dc:type>
    <dc:type xml:lang="en">{{ helpers.map_type(metadata.get('upload_type')) }}</dc:type>

    {% if metadata.keywords %}
    <dc:subject xml:lang="en">{% for keyword in metadata.keywords %}{{ keyword }}{% if not loop.last %}, {% endif %}{% endfor %}</dc:subject>
    {% endif %}

    <dcterms:created>{% if metadata.publication_date %}{{ helpers.iso_date(metadata.publication_date) }}{% endif %}</dcterms:created>

    {% if zenodo.parent and zenodo.parent.id %}
    <dcterms:isPartOf xml:lang="en">https://zenodo.org/records/{{ zenodo.parent.id }}</dcterms:isPartOf>
    {% endif %}

    {% if metadata.locations %}
    {% for loc in metadata.locations %}
    <dcterms:spatial rdf:resource="{{ helpers.generate_uri('place', loc.place + '_' + loop.index|string) }}"/>
    {% endfor %}
    {% endif %}

    <dcterms:temporal>{% if metadata.temporal %}{{ metadata.temporal }}{% endif %}</dcterms:temporal>

    <edm:type>IMAGE</edm:type>
    {% if metadata.doi %}
    <owl:sameAs rdf:resource="https://doi.org/{{ metadata.doi }}"/>
    {% endif %}
  </edm:ProvidedCHO>

  <!-- 2. WebResources -->

  <!-- Landing Page -->
  <edm:WebResource rdf:about="{{ zenodo.links.html | replace('/deposit/', '/records/') }}">
    <dc:format>text/html</dc:format>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </edm:WebResource>

  <!-- Digital Object (Image) -->
  {% if main_file %}
  <edm:WebResource rdf:about="{{ main_file.viewer_url }}"> <!-- For images, viewer_url == content_url in service -->
    {% if metadata.format %}
    <dc:format xml:lang="en">{{ metadata.format }}</dc:format>
    {% else %}
    <dc:format xml:lang="en">image/jpeg</dc:format>
    {% endif %}
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
    <edm:intendedUsage rdf:resource="{{ helpers.normalize_intended_usage_uri(metadata.intended_usage) }}"/>
  </edm:WebResource>
  {% endif %}

  <!-- 3. Agents -->
  {% for creator in metadata.creators %}
  <edm:Agent rdf:about="{{ helpers.generate_uri('agent', creator.name) }}">
    <skos:prefLabel xml:lang="{{ metadata.language | default('en') }}">{{ creator.name }}</skos:prefLabel>
    {% if creator.affiliation %}
    <skos:note>{{ creator.affiliation }}</skos:note>
    {% endif %}
    {% if creator.orcid %}
    <owl:sameAs rdf:resource="https://orcid.org/{{ creator.orcid }}"/>
    {% endif %}
  </edm:Agent>
  {% endfor %}

  <!-- 4. Places -->
  {% if metadata.locations %}
  {% for loc in metadata.locations %}
  <edm:Place rdf:about="{{ helpers.generate_uri('place', loc.place + '_' + loop.index|string) }}">
    {% if loc.lat and loc.lon %}
    <wgs84_pos:lat>{{ loc.lat }}</wgs84_pos:lat>
    <wgs84_pos:long>{{ loc.lon }}</wgs84_pos:long>
    {% endif %}
    <skos:prefLabel xml:lang="{{ metadata.language | default('en') }}">{{ loc.place }}</skos:prefLabel>
    {% if loc.description %}
    <skos:note xml:lang="{{ metadata.language | default('en') }}">{{ loc.description }}</skos:note>
    {% endif %}
  </edm:Place>
  {% endfor %}
  {% endif %}

  <!-- 5. Aggregation -->
  <ore:Aggregation rdf:about="{{ aggregation_uri }}">
    <edm:aggregatedCHO rdf:resource="{{ cho_uri }}"/>
    <edm:dataProvider>{% for creator in metadata.creators %}{{ creator.name }}{% if not loop.last %}, {% endif %}{% endfor %}</edm:dataProvider>
    <edm:isShownAt rdf:resource="{{ zenodo.links.html | replace('/deposit/', '/records/') }}"/>

    {% if main_file %}
    <edm:isShownBy rdf:resource="{{ main_file.viewer_url }}"/>
    {% endif %}

    {% if thumbnail_file %}
    <edm:object rdf:resource="{{ thumbnail_file.content_url }}"/>
    {% endif %}

    <edm:provider>{{ metadata.edm_provider | default('Heritage Data Processor') }}</edm:provider>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </ore:Aggregation>

</rdf:RDF>'''


# =============================================================================
# DOCUMENT TEMPLATE (Publications, Reports - edm:type = TEXT)
# =============================================================================
DOCUMENT_TEMPLATE = '''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:edm="http://www.europeana.eu/schemas/edm/"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:ore="http://www.openarchives.org/ore/terms/"
         xmlns:skos="http://www.w3.org/2004/02/skos/core#"
         xmlns:foaf="http://xmlns.com/foaf/0.1/"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:wgs84_pos="http://www.w3.org/2003/01/geo/wgs84_pos#">

  {% set cho_uri = "https://doi.org/" + metadata.doi if metadata.doi else ("https://doi.org/" + zenodo.metadata.get('prereserve_doi', {}).get('doi') if zenodo.metadata.get('prereserve_doi', {}).get('doi') else zenodo.links.html | replace('/deposit/', '/records/')) %}
  {% set aggregation_uri = cho_uri + "#aggregation" %}

  <edm:ProvidedCHO rdf:about="{{ cho_uri }}">
    <dc:title xml:lang="{{ metadata.language | default('en') }}">{{ metadata.title }}</dc:title>

    {% if metadata.description %}
    <dc:description xml:lang="{{ metadata.language | default('en') }}">{{ metadata.description }}</dc:description>
    {% endif %}

    {% for creator in metadata.creators %}
    <dc:creator rdf:resource="{{ helpers.generate_uri('agent', creator.name) }}"/>
    {% endfor %}

    {% if metadata.publisher %}
    <dc:publisher>{{ metadata.publisher }}</dc:publisher>
    {% endif %}

    {% if metadata.publication_date %}
    <dcterms:issued>{{ helpers.iso_date(metadata.publication_date) }}</dcterms:issued>
    {% endif %}

    <dc:identifier>{{ zenodo.metadata.prereserve_doi.doi }}</dc:identifier>

    {% if metadata.format %}
    <dc:format>{{ metadata.format }}</dc:format>
    {% else %}
    <dc:format>application/pdf</dc:format>
    {% endif %}

    <dc:language>{{ metadata.language | default('en') }}</dc:language>

    <dc:type>Publication</dc:type>
    {% if metadata.get('resource_type') %}
    <dc:type>{{ metadata.get('resource_type') }}</dc:type>
    {% endif %}

    {% if metadata.keywords %}
    {% for keyword in metadata.keywords %}
    <dc:subject>{{ keyword }}</dc:subject>
    {% endfor %}
    {% endif %}

    {% if metadata.locations %}
    {% for loc in metadata.locations %}
    <dcterms:spatial rdf:resource="{{ helpers.generate_uri('place', loc.place + '_' + loop.index|string) }}"/>
    {% endfor %}
    {% endif %}

    {% if metadata.references %}
    {% for ref in metadata.references %}
    <dcterms:references rdf:resource="{{ ref }}"/>
    {% endfor %}
    {% endif %}

    <edm:type>TEXT</edm:type>
    {% if metadata.doi %}
    <owl:sameAs rdf:resource="https://doi.org/{{ metadata.doi }}"/>
    {% endif %}
  </edm:ProvidedCHO>

  <!-- 2. WebResources -->

  <!-- Landing Page -->
  <edm:WebResource rdf:about="{{ zenodo.links.html | replace('/deposit/', '/records/') }}">
     <dc:format>text/html</dc:format>
     <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </edm:WebResource>

  <!-- Digital Object (Document) -->
  {% if main_file %}
  <edm:WebResource rdf:about="{{ main_file.viewer_url }}">
    {% if metadata.format %}
    <dc:format>{{ metadata.format }}</dc:format>
    {% else %}
    <dc:format>application/pdf</dc:format>
    {% endif %}
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
    <edm:intendedUsage rdf:resource="{{ helpers.normalize_intended_usage_uri(metadata.intended_usage) }}"/>
  </edm:WebResource>
  {% endif %}

  <!-- Thumbnail -->
  {% if thumbnail_file %}
  <edm:WebResource rdf:about="{{ thumbnail_file.content_url }}">
    <dc:format>image/jpeg</dc:format>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </edm:WebResource>
  {% endif %}

  <!-- 3. Agents -->
  {% for creator in metadata.creators %}
  <edm:Agent rdf:about="{{ helpers.generate_uri('agent', creator.name) }}">
    <skos:prefLabel xml:lang="{{ metadata.language | default('en') }}">{{ creator.name }}</skos:prefLabel>
    {% if creator.affiliation %}
    <skos:note>{{ creator.affiliation }}</skos:note>
    {% endif %}
    {% if creator.orcid %}
    <owl:sameAs rdf:resource="https://orcid.org/{{ creator.orcid }}"/>
    {% endif %}
  </edm:Agent>
  {% endfor %}

  <!-- 4. Places -->
  {% if metadata.locations %}
  {% for loc in metadata.locations %}
  <edm:Place rdf:about="{{ helpers.generate_uri('place', loc.place + '_' + loop.index|string) }}">
    {% if loc.lat and loc.lon %}
    <wgs84_pos:lat>{{ loc.lat }}</wgs84_pos:lat>
    <wgs84_pos:long>{{ loc.lon }}</wgs84_pos:long>
    {% endif %}
    <skos:prefLabel xml:lang="{{ metadata.language | default('en') }}">{{ loc.place }}</skos:prefLabel>
    {% if loc.description %}
    <skos:note xml:lang="{{ metadata.language | default('en') }}">{{ loc.description }}</skos:note>
    {% endif %}
  </edm:Place>
  {% endfor %}
  {% endif %}

  <!-- 5. Aggregation -->
  <ore:Aggregation rdf:about="{{ aggregation_uri }}">
    <edm:aggregatedCHO rdf:resource="{{ cho_uri }}"/>
    <edm:dataProvider>{{ metadata.provider | default('Zenodo') }}</edm:dataProvider>
    <edm:isShownAt rdf:resource="{{ zenodo.links.html | replace('/deposit/', '/records/') }}"/>

    {% if main_file %}
    <edm:isShownBy rdf:resource="{{ main_file.viewer_url }}"/>
    <edm:hasView rdf:resource="{{ main_file.content_url }}"/>
    {% endif %}

    {% if thumbnail_files %}
    {% for thumb in thumbnail_files %}
    <edm:hasView rdf:resource="{{ thumb.content_url }}"/>
    {% endfor %}
    {% endif %}

    {% if thumbnail_file %}
    <edm:object rdf:resource="{{ thumbnail_file.content_url }}"/>
    {% endif %}

    <edm:provider>{{ metadata.edm_provider | default('Heritage Data Processor') }}</edm:provider>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </ore:Aggregation>

</rdf:RDF>'''

# =============================================================================
# VIDEO TEMPLATE (edm:type = VIDEO)
# =============================================================================
VIDEO_TEMPLATE = '''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:edm="http://www.europeana.eu/schemas/edm/"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:ore="http://www.openarchives.org/ore/terms/"
         xmlns:skos="http://www.w3.org/2004/02/skos/core#"
         xmlns:foaf="http://xmlns.com/foaf/0.1/"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:wgs84_pos="http://www.w3.org/2003/01/geo/wgs84_pos#">

  {% set cho_uri = "https://doi.org/" + metadata.doi if metadata.doi else ("https://doi.org/" + zenodo.metadata.get('prereserve_doi', {}).get('doi') if zenodo.metadata.get('prereserve_doi', {}).get('doi') else zenodo.links.html | replace('/deposit/', '/records/')) %}
  {% set aggregation_uri = cho_uri + "#aggregation" %}

  <edm:ProvidedCHO rdf:about="{{ cho_uri }}">
    <dc:title xml:lang="{{ metadata.language | default('en') }}">{{ metadata.title }}</dc:title>

    {% if metadata.description %}
    <dc:description xml:lang="{{ metadata.language | default('en') }}">{{ metadata.description }}</dc:description>
    {% endif %}

    {% for creator in metadata.creators %}
    <dc:creator rdf:resource="{{ helpers.generate_uri('agent', creator.name) }}"/>
    {% endfor %}

    {% if metadata.format %}
    <dc:format>{{ metadata.format }}</dc:format>
    {% else %}
    <dc:format>video/mp4</dc:format>
    {% endif %}

    <dc:identifier>{{ zenodo.metadata.prereserve_doi.doi }}</dc:identifier>
    <dc:identifier>{{ zenodo.id }}</dc:identifier>

    <dc:type>Video</dc:type>
    {% if metadata.get('resource_type') %}
    <dc:type>{{ metadata.get('resource_type') }}</dc:type>
    {% endif %}

    {% if metadata.keywords %}
    {% for keyword in metadata.keywords %}
    <dc:subject>{{ keyword }}</dc:subject>
    {% endfor %}
    {% endif %}

    {% if metadata.locations %}
    {% for loc in metadata.locations %}
    <dcterms:spatial rdf:resource="{{ helpers.generate_uri('place', loc.place + '_' + loop.index|string) }}"/>
    {% endfor %}
    {% endif %}

    {% if metadata.temporal %}
    <dcterms:temporal>{{ metadata.temporal }}</dcterms:temporal>
    {% endif %}

    <edm:type>VIDEO</edm:type>
    {% if metadata.doi %}
    <owl:sameAs rdf:resource="https://doi.org/{{ metadata.doi }}"/>
    {% endif %}
  </edm:ProvidedCHO>

  <!-- 2. WebResources -->

  <!-- Landing Page -->
  <edm:WebResource rdf:about="{{ zenodo.links.html | replace('/deposit/', '/records/') }}">
    <dc:format>text/html</dc:format>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </edm:WebResource>

  <!-- Digital Object (Video) -->
  {% if main_file %}
  <edm:WebResource rdf:about="{{ main_file.viewer_url }}">
    {% if metadata.format %}
    <dc:format>{{ metadata.format }}</dc:format>
    {% else %}
    <dc:format>video/mp4</dc:format>
    {% endif %}
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
    <edm:intendedUsage rdf:resource="{{ helpers.normalize_intended_usage_uri(metadata.intended_usage) }}"/>
  </edm:WebResource>
  {% endif %}

  <!-- Thumbnail -->
  {% if thumbnail_file %}
  <edm:WebResource rdf:about="{{ thumbnail_file.content_url }}">
    <dc:format>image/jpeg</dc:format>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </edm:WebResource>
  {% endif %}

  <!-- 3. Agents -->
  {% for creator in metadata.creators %}
  <edm:Agent rdf:about="{{ helpers.generate_uri('agent', creator.name) }}">
    <skos:prefLabel xml:lang="{{ metadata.language | default('en') }}">{{ creator.name }}</skos:prefLabel>
    {% if creator.affiliation %}
    <skos:note>{{ creator.affiliation }}</skos:note>
    {% endif %}
    {% if creator.orcid %}
    <owl:sameAs rdf:resource="https://orcid.org/{{ creator.orcid }}"/>
    {% endif %}
  </edm:Agent>
  {% endfor %}

  <!-- 4. Places -->
  {% if metadata.locations %}
  {% for loc in metadata.locations %}
  <edm:Place rdf:about="{{ helpers.generate_uri('place', loc.place + '_' + loop.index|string) }}">
    {% if loc.lat and loc.lon %}
    <wgs84_pos:lat>{{ loc.lat }}</wgs84_pos:lat>
    <wgs84_pos:long>{{ loc.lon }}</wgs84_pos:long>
    {% endif %}
    <skos:prefLabel xml:lang="{{ metadata.language | default('en') }}">{{ loc.place }}</skos:prefLabel>
    {% if loc.description %}
    <skos:note xml:lang="{{ metadata.language | default('en') }}">{{ loc.description }}</skos:note>
    {% endif %}
  </edm:Place>
  {% endfor %}
  {% endif %}

  <!-- 5. Aggregation -->
  <ore:Aggregation rdf:about="{{ aggregation_uri }}">
    <edm:aggregatedCHO rdf:resource="{{ cho_uri }}"/>
    <edm:dataProvider>{{ metadata.provider | default('Zenodo') }}</edm:dataProvider>
    <edm:isShownAt rdf:resource="{{ zenodo.links.html | replace('/deposit/', '/records/') }}"/>

    {% if main_file %}
    <edm:isShownBy rdf:resource="{{ main_file.viewer_url }}"/>
    <edm:hasView rdf:resource="{{ main_file.content_url }}"/>
    {% endif %}

    {% if thumbnail_files %}
    {% for thumb in thumbnail_files %}
    <edm:hasView rdf:resource="{{ thumb.content_url }}"/>
    {% endfor %}
    {% endif %}

    {% if thumbnail_file %}
    <edm:object rdf:resource="{{ thumbnail_file.content_url }}"/>
    {% endif %}

    <edm:provider>{{ metadata.edm_provider | default('Heritage Data Processor') }}</edm:provider>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </ore:Aggregation>

</rdf:RDF>'''


# =============================================================================
# AUDIO/SOUND TEMPLATE (edm:type = SOUND)
# =============================================================================
SOUND_TEMPLATE = '''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:edm="http://www.europeana.eu/schemas/edm/"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:ore="http://www.openarchives.org/ore/terms/"
         xmlns:skos="http://www.w3.org/2004/02/skos/core#"
         xmlns:foaf="http://xmlns.com/foaf/0.1/"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:wgs84_pos="http://www.w3.org/2003/01/geo/wgs84_pos#">

  {% set cho_uri = "https://doi.org/" + metadata.doi if metadata.doi else ("https://doi.org/" + zenodo.metadata.get('prereserve_doi', {}).get('doi') if zenodo.metadata.get('prereserve_doi', {}).get('doi') else zenodo.links.html | replace('/deposit/', '/records/')) %}
  {% set aggregation_uri = cho_uri + "#aggregation" %}

  <edm:ProvidedCHO rdf:about="{{ cho_uri }}">
    <dc:title xml:lang="{{ metadata.language | default('en') }}">{{ metadata.title }}</dc:title>

    {% if metadata.description %}
    <dc:description xml:lang="{{ metadata.language | default('en') }}">{{ metadata.description }}</dc:description>
    {% endif %}

    {% for creator in metadata.creators %}
    <dc:creator rdf:resource="{{ helpers.generate_uri('agent', creator.name) }}"/>
    {% endfor %}

    {% if metadata.format %}
    <dc:format>{{ metadata.format }}</dc:format>
    {% else %}
    <dc:format>audio/mpeg</dc:format>
    {% endif %}

    <dc:identifier>{{ zenodo.metadata.prereserve_doi.doi }}</dc:identifier>
    <dc:identifier>{{ zenodo.id }}</dc:identifier>

    <dc:type>Sound</dc:type>
    {% if metadata.get('resource_type') %}
    <dc:type>{{ metadata.get('resource_type') }}</dc:type>
    {% endif %}

    {% if metadata.keywords %}
    {% for keyword in metadata.keywords %}
    <dc:subject>{{ keyword }}</dc:subject>
    {% endfor %}
    {% endif %}

    {% if metadata.locations %}
    {% for loc in metadata.locations %}
    <dcterms:spatial rdf:resource="{{ helpers.generate_uri('place', loc.place + '_' + loop.index|string) }}"/>
    {% endfor %}
    {% endif %}

    <edm:type>SOUND</edm:type>
    {% if metadata.doi %}
    <owl:sameAs rdf:resource="https://doi.org/{{ metadata.doi }}"/>
    {% endif %}
  </edm:ProvidedCHO>

  <!-- 2. WebResources -->

  <!-- Landing Page -->
  <edm:WebResource rdf:about="{{ zenodo.links.html | replace('/deposit/', '/records/') }}">
    <dc:format>text/html</dc:format>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </edm:WebResource>

  <!-- Digital Object (Audio) -->
  {% if main_file %}
  <edm:WebResource rdf:about="{{ main_file.viewer_url }}">
    {% if metadata.format %}
    <dc:format>{{ metadata.format }}</dc:format>
    {% else %}
    <dc:format>audio/mpeg</dc:format>
    {% endif %}
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
    <edm:intendedUsage rdf:resource="{{ helpers.normalize_intended_usage_uri(metadata.intended_usage) }}"/>
  </edm:WebResource>
  {% endif %}

  <!-- Thumbnail -->
  {% if thumbnail_file %}
  <edm:WebResource rdf:about="{{ thumbnail_file.content_url }}">
    <dc:format>image/jpeg</dc:format>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </edm:WebResource>
  {% endif %}

  <!-- 3. Agents -->
  {% for creator in metadata.creators %}
  <edm:Agent rdf:about="{{ helpers.generate_uri('agent', creator.name) }}">
    <skos:prefLabel xml:lang="{{ metadata.language | default('en') }}">{{ creator.name }}</skos:prefLabel>
    {% if creator.affiliation %}
    <skos:note>{{ creator.affiliation }}</skos:note>
    {% endif %}
    {% if creator.orcid %}
    <owl:sameAs rdf:resource="https://orcid.org/{{ creator.orcid }}"/>
    {% endif %}
  </edm:Agent>
  {% endfor %}

  <!-- 4. Places -->
  {% if metadata.locations %}
  {% for loc in metadata.locations %}
  <edm:Place rdf:about="{{ helpers.generate_uri('place', loc.place + '_' + loop.index|string) }}">
    {% if loc.lat and loc.lon %}
    <wgs84_pos:lat>{{ loc.lat }}</wgs84_pos:lat>
    <wgs84_pos:long>{{ loc.lon }}</wgs84_pos:long>
    {% endif %}
    <skos:prefLabel xml:lang="{{ metadata.language | default('en') }}">{{ loc.place }}</skos:prefLabel>
    {% if loc.description %}
    <skos:note xml:lang="{{ metadata.language | default('en') }}">{{ loc.description }}</skos:note>
    {% endif %}
  </edm:Place>
  {% endfor %}
  {% endif %}

  <!-- 5. Aggregation -->
  <ore:Aggregation rdf:about="{{ aggregation_uri }}">
    <edm:aggregatedCHO rdf:resource="{{ cho_uri }}"/>
    <edm:dataProvider>{{ metadata.provider | default('Zenodo') }}</edm:dataProvider>
    <edm:isShownAt rdf:resource="{{ zenodo.links.html | replace('/deposit/', '/records/') }}"/>

    {% if main_file %}
    <edm:isShownBy rdf:resource="{{ main_file.viewer_url }}"/>
    <edm:hasView rdf:resource="{{ main_file.content_url }}"/>
    {% endif %}

    {% if thumbnail_files %}
    {% for thumb in thumbnail_files %}
    <edm:hasView rdf:resource="{{ thumb.content_url }}"/>
    {% endfor %}
    {% endif %}

    {% if thumbnail_file %}
    <edm:object rdf:resource="{{ thumbnail_file.content_url }}"/>
    {% endif %}

    <edm:provider>{{ metadata.edm_provider | default('Heritage Data Processor') }}</edm:provider>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </ore:Aggregation>

</rdf:RDF>'''

# =============================================================================
# SOFTWARE TEMPLATE (edm:type = TEXT, specialized for software)
# =============================================================================
SOFTWARE_TEMPLATE = '''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:edm="http://www.europeana.eu/schemas/edm/"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:ore="http://www.openarchives.org/ore/terms/"
         xmlns:skos="http://www.w3.org/2004/02/skos/core#"
         xmlns:foaf="http://xmlns.com/foaf/0.1/"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:wgs84_pos="http://www.w3.org/2003/01/geo/wgs84_pos#">

  {% set cho_uri = "https://doi.org/" + metadata.doi if metadata.doi else ("https://doi.org/" + zenodo.metadata.get('prereserve_doi', {}).get('doi') if zenodo.metadata.get('prereserve_doi', {}).get('doi') else zenodo.links.html | replace('/deposit/', '/records/')) %}
  {% set aggregation_uri = cho_uri + "#aggregation" %}

  <edm:ProvidedCHO rdf:about="{{ cho_uri }}">
    <dc:title xml:lang="{{ metadata.language | default('en') }}">{{ metadata.title }}</dc:title>

    {% if metadata.description %}
    <dc:description xml:lang="{{ metadata.language | default('en') }}">{{ metadata.description }}</dc:description>
    {% endif %}

    {% for creator in metadata.creators %}
    <dc:creator rdf:resource="{{ helpers.generate_uri('agent', creator.name) }}"/>
    {% endfor %}

    <dc:identifier>{{ zenodo.metadata.prereserve_doi.doi }}</dc:identifier>
    <dc:identifier>{{ zenodo.id }}</dc:identifier>

    <dc:type>Software</dc:type>
    {% if metadata.get('resource_type') %}
    <dc:type>{{ metadata.get('resource_type') }}</dc:type>
    {% endif %}

    {% if metadata.programming_language %}
    <dc:subject>Programming Language: {{ metadata.programming_language }}</dc:subject>
    {% endif %}

    {% if metadata.keywords %}
    {% for keyword in metadata.keywords %}
    <dc:subject>{{ keyword }}</dc:subject>
    {% endfor %}
    {% endif %}

    {% if metadata.locations %}
    {% for loc in metadata.locations %}
    <dcterms:spatial rdf:resource="{{ helpers.generate_uri('place', loc.place + '_' + loop.index|string) }}"/>
    {% endfor %}
    {% endif %}

    {% if metadata.publication_date %}
    <dcterms:issued>{{ helpers.iso_date(metadata.publication_date) }}</dcterms:issued>
    {% endif %}

    <edm:type>TEXT</edm:type>
    {% if metadata.doi %}
    <owl:sameAs rdf:resource="https://doi.org/{{ metadata.doi }}"/>
    {% endif %}
  </edm:ProvidedCHO>

  <!-- 2. WebResource -->
  <edm:WebResource rdf:about="{{ zenodo.links.html | replace('/deposit/', '/records/') }}">
    <dc:format>text/html</dc:format>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </edm:WebResource>

  <!-- 3. Agents -->
  {% for creator in metadata.creators %}
  <edm:Agent rdf:about="{{ helpers.generate_uri('agent', creator.name) }}">
    <skos:prefLabel xml:lang="{{ metadata.language | default('en') }}">{{ creator.name }}</skos:prefLabel>
    {% if creator.affiliation %}
    <skos:note>{{ creator.affiliation }}</skos:note>
    {% endif %}
    {% if creator.orcid %}
    <owl:sameAs rdf:resource="https://orcid.org/{{ creator.orcid }}"/>
    {% endif %}
  </edm:Agent>
  {% endfor %}

  <!-- 4. Places -->
  {% if metadata.locations %}
  {% for loc in metadata.locations %}
  <edm:Place rdf:about="{{ helpers.generate_uri('place', loc.place + '_' + loop.index|string) }}">
    {% if loc.lat and loc.lon %}
    <wgs84_pos:lat>{{ loc.lat }}</wgs84_pos:lat>
    <wgs84_pos:long>{{ loc.lon }}</wgs84_pos:long>
    {% endif %}
    <skos:prefLabel xml:lang="{{ metadata.language | default('en') }}">{{ loc.place }}</skos:prefLabel>
    {% if loc.description %}
    <skos:note xml:lang="{{ metadata.language | default('en') }}">{{ loc.description }}</skos:note>
    {% endif %}
  </edm:Place>
  {% endfor %}
  {% endif %}

  <!-- 5. Aggregation -->
  <ore:Aggregation rdf:about="{{ aggregation_uri }}">
    <edm:aggregatedCHO rdf:resource="{{ cho_uri }}"/>
    <edm:dataProvider>{{ metadata.provider | default('Zenodo') }}</edm:dataProvider>
    <edm:isShownAt rdf:resource="{{ zenodo.links.html | replace('/deposit/', '/records/') }}"/>
    {% if zenodo.links.download %}
    <edm:isShownBy rdf:resource="{{ zenodo.links.download }}"/>
    {% endif %}
    <edm:object rdf:resource="{{ zenodo.links.html | replace('/deposit/', '/records/') }}"/>
    <edm:provider>{{ metadata.edm_provider | default('Heritage Data Processor') }}</edm:provider>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </ore:Aggregation>

</rdf:RDF>'''

DATASET_TEMPLATE = '''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:edm="http://www.europeana.eu/schemas/edm/"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:ore="http://www.openarchives.org/ore/terms/"
         xmlns:skos="http://www.w3.org/2004/02/skos/core#"
         xmlns:foaf="http://xmlns.com/foaf/0.1/"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:wgs84_pos="http://www.w3.org/2003/01/geo/wgs84_pos#">

  {% set cho_uri = "https://doi.org/" + metadata.doi if metadata.doi else ("https://doi.org/" + zenodo.metadata.get('prereserve_doi', {}).get('doi') if zenodo.metadata.get('prereserve_doi', {}).get('doi') else zenodo.links.html | replace('/deposit/', '/records/')) %}
  {% set aggregation_uri = cho_uri + "#aggregation" %}

  <edm:ProvidedCHO rdf:about="{{ cho_uri }}">
    <dc:title xml:lang="{{ metadata.language | default('en') }}">{{ metadata.title }}</dc:title>

    {% if metadata.description %}
    <dc:description xml:lang="{{ metadata.language | default('en') }}">{{ metadata.description }}</dc:description>
    {% endif %}

    {% for creator in metadata.creators %}
    <dc:creator rdf:resource="{{ helpers.generate_uri('agent', creator.name) }}"/>
    {% endfor %}

    {% if metadata.format %}
    <dc:format>{{ metadata.format }}</dc:format>
    {% endif %}

    <dc:identifier>{{ zenodo.metadata.prereserve_doi.doi }}</dc:identifier>
    <dc:identifier>{{ zenodo.id }}</dc:identifier>

    <dc:language>{{ metadata.language | default('en') }}</dc:language>

    <dc:type>Dataset</dc:type>
    {% if metadata.get('resource_type') %}
    <dc:type>{{ metadata.get('resource_type') }}</dc:type>
    {% endif %}

    {% if metadata.keywords %}
    {% for keyword in metadata.keywords %}
    <dc:subject>{{ keyword }}</dc:subject>
    {% endfor %}
    {% endif %}

    {% if metadata.locations %}
    {% for loc in metadata.locations %}
    <dcterms:spatial rdf:resource="{{ helpers.generate_uri('place', loc.place + '_' + loop.index|string) }}"/>
    {% endfor %}
    {% endif %}

    {% if metadata.temporal %}
    <dcterms:temporal>{{ metadata.temporal }}</dcterms:temporal>
    {% endif %}

    {% if metadata.methodology %}
    <dcterms:provenance>{{ metadata.methodology }}</dcterms:provenance>
    {% endif %}

    <edm:type>TEXT</edm:type>
    {% if metadata.doi %}
    <owl:sameAs rdf:resource="https://doi.org/{{ metadata.doi }}"/>
    {% endif %}
  </edm:ProvidedCHO>

  <!-- 2. WebResource -->
  <edm:WebResource rdf:about="{{ zenodo.links.html | replace('/deposit/', '/records/') }}">
    {% if metadata.format %}
    <dc:format>{{ metadata.format }}</dc:format>
    {% else %}
    <dc:format>application/zip</dc:format>
    {% endif %}
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </edm:WebResource>

  <!-- 3. Agents -->
  {% for creator in metadata.creators %}
  <edm:Agent rdf:about="{{ helpers.generate_uri('agent', creator.name) }}">
    <skos:prefLabel xml:lang="{{ metadata.language | default('en') }}">{{ creator.name }}</skos:prefLabel>
    {% if creator.affiliation %}
    <skos:note>{{ creator.affiliation }}</skos:note>
    {% endif %}
    {% if creator.orcid %}
    <owl:sameAs rdf:resource="https://orcid.org/{{ creator.orcid }}"/>
    {% endif %}
  </edm:Agent>
  {% endfor %}

  <!-- 4. Places -->
  {% if metadata.locations %}
  {% for loc in metadata.locations %}
  <edm:Place rdf:about="{{ helpers.generate_uri('place', loc.place + '_' + loop.index|string) }}">
    {% if loc.lat and loc.lon %}
    <wgs84_pos:lat>{{ loc.lat }}</wgs84_pos:lat>
    <wgs84_pos:long>{{ loc.lon }}</wgs84_pos:long>
    {% endif %}
    <skos:prefLabel xml:lang="{{ metadata.language | default('en') }}">{{ loc.place }}</skos:prefLabel>
    {% if loc.description %}
    <skos:note xml:lang="{{ metadata.language | default('en') }}">{{ loc.description }}</skos:note>
    {% endif %}
  </edm:Place>
  {% endfor %}
  {% endif %}

  <!-- 5. Aggregation -->
  <ore:Aggregation rdf:about="{{ aggregation_uri }}">
    <edm:aggregatedCHO rdf:resource="{{ cho_uri }}"/>
    <edm:dataProvider>{{ metadata.provider | default('Zenodo') }}</edm:dataProvider>
    <edm:isShownAt rdf:resource="{{ zenodo.links.html | replace('/deposit/', '/records/') }}"/>
    {% if zenodo.links.download %}
    <edm:isShownBy rdf:resource="{{ zenodo.links.download }}"/>
    {% endif %}
    <edm:object rdf:resource="{{ zenodo.links.html | replace('/deposit/', '/records/') }}"/>
    <edm:provider>{{ metadata.edm_provider | default('Heritage Data Processor') }}</edm:provider>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </ore:Aggregation>

</rdf:RDF>'''



# Template definitions with metadata
TEMPLATES = [
    {
        "name": "Standard EDM Template",
        "description": "Optimized general-purpose template following Europeana best practices. Includes Agent/Place nodes, WebResource, and all mandatory fields.",
        "content": STANDARD_TEMPLATE,
        "is_default": True
    },
    {
        "name": "3D Model",
        "description": "Template for 3D scans and models (GLB, GLTF, OBJ, STL). Uses edm:type=3D with support for Agent/Place nodes and original object metadata.",
        "content": MODEL_3D_TEMPLATE,
        "is_default": False
    },
    {
        "name": "Photography / Image",
        "description": "Template for photographs, artwork scans, and digital images. Uses edm:type=IMAGE with Agent/Place nodes and temporal context support.",
        "content": IMAGE_TEMPLATE,
        "is_default": False
    },
    {
        "name": "Document / Publication",
        "description": "Template for PDFs, publications, and text documents. Uses edm:type=TEXT with Agent/Place nodes and publisher support.",
        "content": DOCUMENT_TEMPLATE,
        "is_default": False
    },
    {
        "name": "Video",
        "description": "Template for video recordings (MP4, MOV, etc.). Uses edm:type=VIDEO with Agent/Place nodes, duration and language support.",
        "content": VIDEO_TEMPLATE,
        "is_default": False
    },
    {
        "name": "Audio / Sound",
        "description": "Template for audio recordings and music (MP3, WAV, FLAC). Uses edm:type=SOUND with Agent/Place nodes and duration.",
        "content": SOUND_TEMPLATE,
        "is_default": False
    },
    {
        "name": "Software",
        "description": "Template for software packages and code. Uses edm:type=DATASET with Agent/Place nodes, version, and repository links.",
        "content": SOFTWARE_TEMPLATE,
        "is_default": False
    },
    {
        "name": "Dataset",
        "description": "Template for research datasets and data collections. Uses edm:type=TEXT with Agent/Place nodes, spatial/temporal coverage and methodology.",
        "content": DATASET_TEMPLATE,
        "is_default": False
    },
]


def seed_templates(clear_existing=False):
    """
    Seeds the database with optimized EDM templates.

    Args:
        clear_existing: If True, deletes all existing templates before seeding.

    Returns:
        dict: Summary of operations performed.
    """
    result = {
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "errors": []
    }

    try:
        if clear_existing:
            EdmTemplate.query.delete()
            db.session.commit()
            logger.info("Cleared existing templates")

        for tpl_data in TEMPLATES:
            try:
                # Check if template with this name exists
                template = LodTemplate.query.filter_by(name=tpl_data["name"]).first()

                if template:
                    # Update existing template
                    template.description = tpl_data["description"]
                    template.content = tpl_data["content"]
                    template.is_default = tpl_data["is_default"]
                    result["updated"] += 1
                    logger.info(f"Updated template: {tpl_data['name']}")
                else:
                    # Create new template
                    # Use LodTemplate
                    template = LodTemplate(
                        name=tpl_data["name"],
                        description=tpl_data["description"],
                        standard=LodStandard.EDM,
                        format="xml",
                        content=tpl_data["content"],
                        is_default=tpl_data["is_default"]
                    )
                    db.session.add(template)
                    result["created"] += 1
                    logger.info(f"Created template: {tpl_data['name']}")

            except Exception as e:
                result["errors"].append(f"{tpl_data['name']}: {str(e)}")
                logger.error(f"Error with template {tpl_data['name']}: {e}")

        db.session.commit()
        logger.info(f"Template seeding complete: {result}")

    except Exception as e:
        db.session.rollback()
        result["errors"].append(str(e))
        logger.error(f"Template seeding failed: {e}")

    return result


if __name__ == "__main__":
    # For running outside Flask context
    from flask import Flask
    from config import Config

    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    with app.app_context():
        result = seed_templates(clear_existing=True)
        print(f"Seeding result: {result}")
