# services/mets_service.py
import logging
import json
import re
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import jinja2
from services.edm_service import EdmService, DotDict

logger = logging.getLogger(__name__)


class MetsService:
    """
    Service for generating METS (Metadata Encoding and Transmission Standard) XML files
    with embedded MODS (Metadata Object Description Schema) metadata.
    """

    def __init__(self):
        self.edm_service = EdmService()  # Reuse helper methods from EdmService
        self.namespaces = {
            "mets": "http://www.loc.gov/METS/",
            "mods": "http://www.loc.gov/mods/v3",
            "xlink": "http://www.w3.org/1999/xlink",
        }
        self._schema_cache = {}

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _schema_parser(self):
        from lxml import etree

        repo_root = self._repo_root()

        class LocalSchemaResolver(etree.Resolver):
            def resolve(self, url, pubid, context):
                if url in {
                    "http://www.loc.gov/standards/xlink/xlink.xsd",
                    "http://www.loc.gov/standards/mets/xlink.xsd",
                    "xlink.xsd",
                }:
                    return self.resolve_filename(str(repo_root / "docs" / "metsmods" / "xlink.xsd"), context)
                if url in {
                    "http://www.loc.gov/mods/xml.xsd",
                    "http://www.w3.org/2001/xml.xsd",
                }:
                    return self.resolve_filename(str(repo_root / "schema_xsds" / "xml.xsd"), context)
                return None

        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        parser.resolvers.add(LocalSchemaResolver())
        return parser

    def _get_xml_schema(self, schema_name: str):
        from lxml import etree

        if schema_name not in self._schema_cache:
            schema_paths = {
                "mets": self._repo_root() / "docs" / "metsmods" / "mets.xsd.xml",
                "mods": self._repo_root() / "docs" / "metsmods" / "mods-3-8.xsd.xml",
            }
            schema_path = schema_paths[schema_name]
            schema_doc = etree.parse(str(schema_path), self._schema_parser())
            self._schema_cache[schema_name] = etree.XMLSchema(schema_doc)
        return self._schema_cache[schema_name]

    def map_mods_type(self, content_type: str) -> str:
        """Maps internal content type to MODS resource type."""
        mapping = {
            '3d_model': 'software, multimedia',
            'image': 'still image',
            'video': 'moving image',
            'audio': 'sound recording',
            'document': 'text',
            'data': 'dataset'
        }
        return mapping.get(content_type, 'software, multimedia')

    def map_structure_type(self, content_type: str) -> str:
        """Maps internal content type to METS structMap TYPE."""
        return content_type.upper() if content_type else "mixed"

    def iso_date_full(self, date_str: str) -> str:
        """Returns ISO 8601 date with time (or defaults to T00:00:00Z if only date provided)."""
        clean_date = self.edm_service.iso_date(date_str)
        if len(clean_date) == 10:
             return f"{clean_date}T00:00:00Z"
        return clean_date

    def now_iso(self) -> str:
        """Returns current UTC time in ISO format."""
        return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    def _is_iso8601_calendar_date(self, value: str) -> bool:
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value or "").strip()))

    def _is_unknown_date_value(self, value: Any) -> bool:
        text = str(value or "").strip().lower()
        return text in {"", "unknown", "n/a", "na", "none", "undated"}

    def _safe_file_id(self, filename: str, role: str = "FILE") -> str:
        """Keep XML IDs valid and distinct across filenames and asset roles."""
        digest = hashlib.sha256(str(filename or "unknown").encode("utf-8")).hexdigest()
        return f"{role}_{digest}"

    def _prepare_mets_assets(
        self,
        metadata: Dict[str, Any],
        zenodo_record: Dict[str, Any],
        main_file_key: Optional[str] = None,
        allow_placeholder_thumbnail: bool = False,
        additional_files: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        files = self.edm_service._normalize_zenodo_files(zenodo_record)
        if additional_files:
            files.extend(additional_files)

        z_copy = zenodo_record.copy() if isinstance(zenodo_record, dict) else {}
        z_copy["files"] = files

        main_file = None
        if main_file_key:
            main_file = next(
                (f for f in files if (f.get("key") or f.get("filename")) == main_file_key),
                None,
            )
            if not main_file:
                main_file = {"key": main_file_key, "filename": main_file_key, "size": 0}
        if not main_file:
            main_file = self.edm_service._select_smart_primary_file(files, metadata)
        if not main_file:
            main_file = {"key": "unknown_file", "filename": "unknown_file", "size": 0}

        thumbnail_files = self.edm_service._select_thumbnail_files(
            files,
            main_file=main_file,
            metadata=metadata,
            allow_placeholder=allow_placeholder_thumbnail,
        )

        main_file = self.edm_service._enrich_file_metadata(main_file, metadata)
        record_id = str(z_copy.get("id", ""))
        zenodo_url = self.edm_service.get_record_html_url(z_copy)
        z_copy["zenodo_url"] = zenodo_url
        is_sandbox_mode = "sandbox.zenodo.org" in zenodo_url

        main_file["content_url"] = self.edm_service.get_file_content_url(
            main_file,
            record_id,
            is_sandbox=is_sandbox_mode,
        )
        main_file["viewer_url"] = main_file["content_url"]

        enriched_thumbnail_files: List[Dict[str, Any]] = []
        for thumb in thumbnail_files:
            enriched_thumb = self.edm_service._enrich_file_metadata(thumb, metadata)
            enriched_thumb["content_url"] = self.edm_service.get_file_content_url(
                enriched_thumb,
                record_id,
                is_sandbox=is_sandbox_mode,
            )
            enriched_thumbnail_files.append(enriched_thumb)

        return {
            "zenodo_record": z_copy,
            "main_file": main_file,
            "thumbnail_files": enriched_thumbnail_files,
            "thumbnail_file": enriched_thumbnail_files[0] if enriched_thumbnail_files else None,
        }

    def _ensure_minimum_viable_mets(
        self,
        rendered_xml: str,
        metadata: Dict[str, Any],
        zenodo_record: Dict[str, Any],
        *,
        main_file_key: Optional[str] = None,
        allow_placeholder_thumbnail: bool = False,
        additional_files: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        try:
            from lxml import etree
        except Exception:
            return rendered_xml

        try:
            parser = etree.XMLParser(resolve_entities=False, no_network=True)
            root = etree.fromstring(rendered_xml.encode("utf-8"), parser=parser)
        except Exception:
            return rendered_xml

        ns = self.namespaces
        assets = self._prepare_mets_assets(
            metadata,
            zenodo_record,
            main_file_key=main_file_key,
            allow_placeholder_thumbnail=allow_placeholder_thumbnail,
            additional_files=additional_files,
        )
        main_file = assets["main_file"]
        thumbnail_files = assets["thumbnail_files"]
        zenodo_context = assets["zenodo_record"]

        xlink_href = f"{{{ns['xlink']}}}href"

        fallback_title = str(metadata.get("title") or "Untitled record").strip() or "Untitled record"
        root.set("OBJID", root.get("OBJID") or f"hdp:{zenodo_context.get('id', 'unknown')}")
        root.set("LABEL", root.get("LABEL") or fallback_title)

        mets_hdr = root.find(f"{{{ns['mets']}}}metsHdr")
        if mets_hdr is None:
            mets_hdr = etree.SubElement(root, f"{{{ns['mets']}}}metsHdr")
        mets_hdr.set("CREATEDATE", mets_hdr.get("CREATEDATE") or self.now_iso())
        mets_hdr.set("LASTMODDATE", self.now_iso())
        mets_hdr.set("RECORDSTATUS", mets_hdr.get("RECORDSTATUS") or "Active")

        agent_name = str(metadata.get("edm_provider") or metadata.get("provider") or "Heritage Data Processor").strip()
        creator_agent = mets_hdr.find(f"{{{ns['mets']}}}agent")
        if creator_agent is None:
            creator_agent = etree.SubElement(mets_hdr, f"{{{ns['mets']}}}agent", ROLE="CREATOR", TYPE="ORGANIZATION")
        creator_name = creator_agent.find(f"{{{ns['mets']}}}name")
        if creator_name is None:
            creator_name = etree.SubElement(creator_agent, f"{{{ns['mets']}}}name")
        if not str(creator_name.text or "").strip():
            creator_name.text = agent_name

        dmd_sec = root.find(f"{{{ns['mets']}}}dmdSec")
        if dmd_sec is None:
            dmd_sec = etree.SubElement(root, f"{{{ns['mets']}}}dmdSec", ID="dmdSec_1")
        elif not dmd_sec.get("ID"):
            dmd_sec.set("ID", "dmdSec_1")

        md_wrap = dmd_sec.find(f"{{{ns['mets']}}}mdWrap")
        if md_wrap is None:
            md_wrap = etree.SubElement(dmd_sec, f"{{{ns['mets']}}}mdWrap", MDTYPE="MODS")
        elif not md_wrap.get("MDTYPE"):
            md_wrap.set("MDTYPE", "MODS")

        xml_data = md_wrap.find(f"{{{ns['mets']}}}xmlData")
        if xml_data is None:
            xml_data = etree.SubElement(md_wrap, f"{{{ns['mets']}}}xmlData")

        mods = xml_data.find(f"{{{ns['mods']}}}mods")
        if mods is None:
            mods = etree.SubElement(xml_data, f"{{{ns['mods']}}}mods")

        title_info = mods.find(f"{{{ns['mods']}}}titleInfo")
        if title_info is None:
            title_info = etree.SubElement(mods, f"{{{ns['mods']}}}titleInfo")
        title = title_info.find(f"{{{ns['mods']}}}title")
        if title is None:
            title = etree.SubElement(title_info, f"{{{ns['mods']}}}title")
        if not str(title.text or "").strip():
            title.text = fallback_title

        resource_type = mods.find(f"{{{ns['mods']}}}typeOfResource")
        if resource_type is None:
            resource_type = etree.SubElement(mods, f"{{{ns['mods']}}}typeOfResource")
        if not str(resource_type.text or "").strip():
            resource_type.text = self.map_mods_type(main_file.get("content_type"))

        origin_info = mods.find(f"{{{ns['mods']}}}originInfo")
        if origin_info is None:
            origin_info = etree.SubElement(mods, f"{{{ns['mods']}}}originInfo")
        date_created = origin_info.find(f"{{{ns['mods']}}}dateCreated")
        raw_created = str(metadata.get("cho_created") or metadata.get("dcterms:created") or "").strip()
        normalized_created = self.edm_service.iso_date(raw_created) if raw_created else ""
        created_text = normalized_created if self._is_iso8601_calendar_date(normalized_created) else raw_created
        if created_text and not self._is_unknown_date_value(created_text):
            if date_created is None:
                date_created = etree.SubElement(origin_info, f"{{{ns['mods']}}}dateCreated")
            if self._is_iso8601_calendar_date(created_text):
                date_created.set("encoding", "iso8601")
            else:
                date_created.attrib.pop("encoding", None)
            if not str(date_created.text or "").strip():
                date_created.text = created_text
        elif date_created is not None:
            origin_info.remove(date_created)

        date_issued = origin_info.find(f"{{{ns['mods']}}}dateIssued")
        publication_date = self.edm_service.iso_date(str(metadata.get("publication_date") or ""))
        if publication_date:
            if date_issued is None:
                date_issued = etree.SubElement(origin_info, f"{{{ns['mods']}}}dateIssued", encoding="iso8601")
            if not date_issued.get("encoding"):
                date_issued.set("encoding", "iso8601")
            if not str(date_issued.text or "").strip():
                date_issued.text = publication_date
        elif date_issued is not None and not str(date_issued.text or "").strip():
            origin_info.remove(date_issued)
        publisher = origin_info.find(f"{{{ns['mods']}}}publisher")
        if publisher is None:
            publisher = etree.SubElement(origin_info, f"{{{ns['mods']}}}publisher")
        if not str(publisher.text or "").strip():
            publisher.text = str(metadata.get("provider") or "Zenodo")

        access_condition = mods.find(f"{{{ns['mods']}}}accessCondition")
        if access_condition is None:
            access_condition = etree.SubElement(mods, f"{{{ns['mods']}}}accessCondition", type="use and reproduction")
        if not str(access_condition.text or "").strip():
            access_condition.text = str(metadata.get("license") or "Unknown")

        file_sec = root.find(f"{{{ns['mets']}}}fileSec")
        if file_sec is None:
            file_sec = etree.SubElement(root, f"{{{ns['mets']}}}fileSec")

        original_group = None
        for file_grp in file_sec.findall(f"{{{ns['mets']}}}fileGrp"):
            if file_grp.get("USE") == "ORIGINAL":
                original_group = file_grp
                break
        if original_group is None:
            original_group = etree.SubElement(file_sec, f"{{{ns['mets']}}}fileGrp", USE="ORIGINAL")

        original_file = original_group.find(f"{{{ns['mets']}}}file")
        if original_file is None:
            original_file = etree.SubElement(original_group, f"{{{ns['mets']}}}file")
        original_file.set("ID", original_file.get("ID") or self._safe_file_id(main_file.get("filename")))
        original_file.set("MIMETYPE", original_file.get("MIMETYPE") or str(main_file.get("mime_type") or "application/octet-stream"))
        size_value = str(main_file.get("size") or "").strip()
        if size_value and size_value != "0":
            original_file.set("SIZE", original_file.get("SIZE") or size_value)
        elif "SIZE" in original_file.attrib:
            del original_file.attrib["SIZE"]

        checksum_value = str(main_file.get("checksum") or "").strip()
        checksum_type = str(main_file.get("checksum_type") or "").strip().upper()
        if checksum_value and checksum_type:
            original_file.set("CHECKSUM", original_file.get("CHECKSUM") or checksum_value)
            original_file.set("CHECKSUMTYPE", original_file.get("CHECKSUMTYPE") or checksum_type)
        else:
            if "CHECKSUM" in original_file.attrib:
                del original_file.attrib["CHECKSUM"]
            if "CHECKSUMTYPE" in original_file.attrib:
                del original_file.attrib["CHECKSUMTYPE"]
        flocat = original_file.find(f"{{{ns['mets']}}}FLocat")
        if flocat is None:
            flocat = etree.SubElement(original_file, f"{{{ns['mets']}}}FLocat", LOCTYPE="URL")
        if not flocat.get("LOCTYPE"):
            flocat.set("LOCTYPE", "URL")
        flocat.set(xlink_href, str(main_file.get("content_url") or main_file.get("viewer_url") or ""))

        if thumbnail_files:
            thumb_group = None
            for file_grp in file_sec.findall(f"{{{ns['mets']}}}fileGrp"):
                if file_grp.get("USE") == "THUMBNAIL":
                    thumb_group = file_grp
                    break
            if thumb_group is None:
                thumb_group = etree.SubElement(file_sec, f"{{{ns['mets']}}}fileGrp", USE="THUMBNAIL")
            existing_ids = {
                file_node.get("ID")
                for file_node in thumb_group.findall(f"{{{ns['mets']}}}file")
                if file_node.get("ID")
            }
            for thumb in thumbnail_files:
                thumb_id = self._safe_file_id(thumb.get("filename"), "THUMB")
                if thumb_id in existing_ids:
                    continue
                thumb_file = etree.SubElement(
                    thumb_group,
                    f"{{{ns['mets']}}}file",
                    ID=thumb_id,
                    MIMETYPE=str(thumb.get("mime_type") or "image/png"),
                )
                thumb_size = str(thumb.get("size") or "").strip()
                if thumb_size and thumb_size != "0":
                    thumb_file.set("SIZE", thumb_size)
                etree.SubElement(
                    thumb_file,
                    f"{{{ns['mets']}}}FLocat",
                    LOCTYPE="URL",
                ).set(xlink_href, str(thumb.get("content_url") or ""))

        struct_map = root.find(f"{{{ns['mets']}}}structMap")
        if struct_map is None:
            struct_map = etree.SubElement(root, f"{{{ns['mets']}}}structMap", TYPE="LOGICAL")
        elif not struct_map.get("TYPE"):
            struct_map.set("TYPE", "LOGICAL")

        div = struct_map.find(f"{{{ns['mets']}}}div")
        if div is None:
            div = etree.SubElement(
                struct_map,
                f"{{{ns['mets']}}}div",
                TYPE=self.map_structure_type(main_file.get("content_type")),
                DMDID=dmd_sec.get("ID"),
                LABEL=fallback_title,
            )
        else:
            div.set("TYPE", div.get("TYPE") or self.map_structure_type(main_file.get("content_type")))
            div.set("DMDID", div.get("DMDID") or dmd_sec.get("ID"))
            div.set("LABEL", div.get("LABEL") or fallback_title)

        if not div.findall(f"{{{ns['mets']}}}fptr"):
            etree.SubElement(div, f"{{{ns['mets']}}}fptr", FILEID=original_file.get("ID"))

        return etree.tostring(root, encoding="unicode")

    def validate_mets_xml(self, xml_string: str) -> Dict[str, Any]:
        result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "details": {},
        }
        try:
            from lxml import etree
        except Exception as exc:
            result["valid"] = False
            result["errors"].append(f"lxml is required for METS validation: {exc}")
            return result

        try:
            parser = etree.XMLParser(resolve_entities=False, no_network=True)
            root = etree.fromstring(xml_string.encode("utf-8"), parser=parser)
        except etree.XMLSyntaxError as exc:
            result["valid"] = False
            result["errors"].append(f"XML Syntax Error: {exc}")
            return result

        ns = self.namespaces
        xlink_href = f"{{{ns['xlink']}}}href"

        xsd_details = {
            "mets_schema": "docs/metsmods/mets.xsd.xml",
            "mods_schema": "docs/metsmods/mods-3-8.xsd.xml",
            "valid": True,
            "errors": [],
        }
        try:
            mets_schema = self._get_xml_schema("mets")
            if not mets_schema.validate(root):
                xsd_details["valid"] = False
                for entry in mets_schema.error_log:
                    xsd_details["errors"].append(f"METS XSD: line {entry.line}: {entry.message}")
            mods_schema = self._get_xml_schema("mods")
            for mods_node in root.findall(f".//{{{ns['mods']}}}mods"):
                if not mods_schema.validate(mods_node):
                    xsd_details["valid"] = False
                    for entry in mods_schema.error_log:
                        xsd_details["errors"].append(f"MODS XSD: line {entry.line}: {entry.message}")
        except Exception as exc:
            xsd_details["valid"] = False
            xsd_details["errors"].append(f"METS/MODS XSD validation could not run: {exc}")

        result["details"]["xsd"] = xsd_details
        if not xsd_details["valid"]:
            result["valid"] = False
            result["errors"].extend(xsd_details["errors"])

        if root.tag != f"{{{ns['mets']}}}mets":
            result["valid"] = False
            result["errors"].append("Root element must be mets:mets.")

        if not root.get("OBJID"):
            result["valid"] = False
            result["errors"].append("METS root must include OBJID.")
        if not root.get("LABEL"):
            result["warnings"].append("METS root should include LABEL.")

        mets_hdr = root.find(f"{{{ns['mets']}}}metsHdr")
        if mets_hdr is None:
            result["valid"] = False
            result["errors"].append("METS must include metsHdr.")
        else:
            if not mets_hdr.get("CREATEDATE"):
                result["valid"] = False
                result["errors"].append("metsHdr must include CREATEDATE.")
            if not mets_hdr.findall(f"{{{ns['mets']}}}agent"):
                result["warnings"].append("metsHdr should include at least one mets:agent.")

        mods = root.find(f".//{{{ns['mods']}}}mods")
        if mods is None:
            result["valid"] = False
            result["errors"].append("METS must embed MODS metadata in dmdSec.")
        else:
            title = mods.find(f".//{{{ns['mods']}}}title")
            if title is None or not str(title.text or "").strip():
                result["valid"] = False
                result["errors"].append("MODS metadata must include a non-empty title.")
            if mods.find(f".//{{{ns['mods']}}}typeOfResource") is None:
                result["warnings"].append("MODS metadata should include typeOfResource.")

        file_nodes = root.findall(f".//{{{ns['mets']}}}file")
        if not file_nodes:
            result["valid"] = False
            result["errors"].append("METS fileSec must include at least one mets:file.")
            return result

        file_ids = set()
        for file_node in file_nodes:
            file_id = file_node.get("ID")
            if not file_id:
                result["valid"] = False
                result["errors"].append("Every mets:file must define an ID.")
                continue
            if file_id in file_ids:
                result["valid"] = False
                result["errors"].append(f"Duplicate mets:file ID detected: {file_id}")
            file_ids.add(file_id)

            if not file_node.get("MIMETYPE"):
                result["valid"] = False
                result["errors"].append(f"mets:file {file_id} is missing MIMETYPE.")
            flocat = file_node.find(f"{{{ns['mets']}}}FLocat")
            if flocat is None or not flocat.get(xlink_href):
                result["valid"] = False
                result["errors"].append(f"mets:file {file_id} must include FLocat with xlink:href.")

        struct_map = root.find(f"{{{ns['mets']}}}structMap")
        if struct_map is None:
            result["valid"] = False
            result["errors"].append("METS must include structMap.")
            return result

        div = struct_map.find(f"{{{ns['mets']}}}div")
        if div is None:
            result["valid"] = False
            result["errors"].append("structMap must include a top-level mets:div.")
            return result

        fptrs = div.findall(f".//{{{ns['mets']}}}fptr")
        if not fptrs:
            result["valid"] = False
            result["errors"].append("structMap must contain at least one mets:fptr.")
        else:
            for fptr in fptrs:
                file_id = fptr.get("FILEID")
                if not file_id:
                    result["valid"] = False
                    result["errors"].append("mets:fptr must include FILEID.")
                elif file_id not in file_ids:
                    result["valid"] = False
                    result["errors"].append(f"mets:fptr references unknown FILEID: {file_id}")

        thumb_groups = [
            group
            for group in root.findall(f".//{{{ns['mets']}}}fileGrp")
            if group.get("USE") == "THUMBNAIL"
        ]
        if not thumb_groups:
            result["warnings"].append("METS has no THUMBNAIL fileGrp.")

        result["details"]["file_count"] = len(file_nodes)
        result["details"]["thumbnail_group_count"] = len(thumb_groups)
        result["details"]["struct_pointer_count"] = len(fptrs)
        return result

    def render_template(
        self,
        template_id: int,
        metadata: Dict[str, Any],
        zenodo_record: Dict[str, Any],
        main_file_key: Optional[str] = None,
        allow_placeholder_thumbnail: bool = False,
        additional_files: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[str]:
        """
        Renders a METS XML from a stored Jinja2 template.
        """
        from database.database import db
        from database.models import LodTemplate

        try:
            template = db.session.get(LodTemplate, template_id)
            if not template:
                logger.error(f"LodTemplate {template_id} not found.")
                return None

            assets = self._prepare_mets_assets(
                metadata,
                zenodo_record,
                main_file_key=main_file_key,
                allow_placeholder_thumbnail=allow_placeholder_thumbnail,
                additional_files=additional_files,
            )
            zenodo_record = assets["zenodo_record"]
            main_file = assets["main_file"]
            enriched_thumbnail_files = assets["thumbnail_files"]
            thumbnail_file = assets["thumbnail_file"]

            # 5. Prepare Jinja2 Environment
            # METS is XML, so keep autoescaping enabled to avoid invalid output
            # when metadata contains characters like '&', '<', or '>'.
            env = jinja2.Environment(autoescape=True, undefined=jinja2.DebugUndefined)

            # Context Helpers
            helpers = {
                'iso_date': self.edm_service.iso_date,
                'iso_date_full': self.iso_date_full,
                'now_iso': self.now_iso,
                'map_mods_type': self.map_mods_type,
                'map_structure_type': self.map_structure_type,
                'file_id': self._safe_file_id,
            }

            jinja_template = env.from_string(template.content)

            # Wrap in DotDicts
            zenodo_dict = DotDict(zenodo_record) if isinstance(zenodo_record, dict) else zenodo_record
            meta_dict = DotDict(metadata) if isinstance(metadata, dict) else metadata
            main_dict = DotDict(main_file) if isinstance(main_file, dict) else main_file
            thumb_dict = DotDict(thumbnail_file) if isinstance(thumbnail_file, dict) and thumbnail_file else None
            thumb_list_dict = [DotDict(thumb) for thumb in enriched_thumbnail_files]

            rendered_xml = jinja_template.render(
                metadata=meta_dict,
                zenodo=zenodo_dict,
                helpers=helpers,
                main_file=main_dict,
                thumbnail_file=thumb_dict,
                thumbnail_files=thumb_list_dict,
            )

            return rendered_xml

        except Exception as e:
            logger.error(f"METS Template rendering failed: {e}", exc_info=True)
            return None

    def generate_mets_xml(
        self,
        metadata: Dict[str, Any],
        zenodo_record: Dict[str, Any],
        template_id: Optional[int] = None,
        main_file_key: Optional[str] = None,
        validate: bool = True,
        allow_placeholder_thumbnail: bool = False,
        additional_files: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Main entry point for generating METS XML.
        """
        result = self.generate_mets_xml_with_report(
            metadata=metadata,
            zenodo_record=zenodo_record,
            template_id=template_id,
            main_file_key=main_file_key,
            validate=validate,
            allow_placeholder_thumbnail=allow_placeholder_thumbnail,
            additional_files=additional_files,
        )
        return result["content"]

    def generate_mets_xml_with_report(
        self,
        metadata: Dict[str, Any],
        zenodo_record: Dict[str, Any],
        template_id: Optional[int] = None,
        main_file_key: Optional[str] = None,
        validate: bool = True,
        allow_placeholder_thumbnail: bool = False,
        additional_files: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Generates a METS document and reports whether minimum-viable safeguards
        altered the rendered template output.
        """
        from database.lod_template_bootstrap import ensure_default_lod_templates
        from database.database import db
        from database.models import LodTemplate, LodStandard

        ensure_default_lod_templates()

        if template_id:
            requested = db.session.get(LodTemplate, template_id)
            requested_standard = getattr(getattr(requested, "standard", None), "value", None)
            if not requested or requested_standard != LodStandard.METS.value:
                template_id = None

        if not template_id:
            # Use default METS template
            default = LodTemplate.query.filter_by(is_default=True, standard=LodStandard.METS).first()
            if default:
                template_id = default.id
            else:
                first = LodTemplate.query.filter_by(standard=LodStandard.METS).first()
                if first:
                    template_id = first.id
                else:
                    raise ValueError("No METS templates found in database")

        rendered = self.render_template(
            template_id,
            metadata,
            zenodo_record,
            main_file_key=main_file_key,
            allow_placeholder_thumbnail=allow_placeholder_thumbnail,
            additional_files=additional_files,
        )
        if not rendered:
            raise ValueError("METS Template rendering returned empty result")

        repaired = self._ensure_minimum_viable_mets(
            rendered,
            metadata,
            zenodo_record,
            main_file_key=main_file_key,
            allow_placeholder_thumbnail=allow_placeholder_thumbnail,
            additional_files=additional_files,
        )
        minimum_viable_applied = repaired != rendered

        validation = None
        if validate:
            validation = self.validate_mets_xml(repaired)
            if not validation["valid"]:
                error_summary = "; ".join(validation["errors"][:3])
                raise ValueError(f"METS validation failed: {error_summary}")

        return {
            "content": repaired,
            "minimum_viable_applied": minimum_viable_applied,
            "validation": validation,
        }
