# Glossary

| Term | Meaning in WebHDP |
|---|---|
| Session | A bounded processing context for one ingestion and submission lifecycle |
| MSF | Metadata Source File (Excel/CSV) used to map metadata to assets |
| `.hdpc` | Session-specific SQLite project file used directly by WebHDP as the local project state |
| LOD Template | Jinja-based template used to generate EDM/IIIF/METS outputs |
| Provenance | Traceable mapping of source files, metadata, and pipeline steps to final records |
| Pipeline | Ordered execution steps (render, conversion, metadata generation, upload) |
| HDP Component | Separate executable package described by `component.yaml`; WebHDP installs, registers, orchestrates, and records it rather than importing it as application code |
| Built-in WebHDP Component | Processing behavior that ships with the main WebHDP application and supports the stable publication workflow |
| External HDP Component | Separately installable component package, commonly distributed as a Docker image for local execution or a SIF image for HPC execution |
| Execution Profile | Manifest entry that tells WebHDP which adapter, runtime, image, and entrypoint to use for a component run |
| `local_container` | Installation strategy for Docker-backed HDP Components on a trusted workstation-local or lab deployment |
| `hpc_sif` | Installation strategy for Singularity/Apptainer SIF-backed HDP Components installed and tested through HPC-Link |
| SIF | Singularity Image File used to distribute a containerized component for HPC execution |
| Source Asset | Original scholarly or collection file selected for processing and provenance tracking |
| Derivative Asset | Generated file such as a normalized GLB, repaired model, optimized LOD, preview, or report created from a source asset |
| Prepublication Analysis | Optional non-mutating 3D pipeline phase that produces technical reports before publication or derivative generation |
| Viewer Readiness | Technical assessment of whether a model is likely to perform well in web viewers, including size, textures, draw calls, and format risk |
| Point-Cloud Readiness | Assessment of point-cloud structure, counts, fields, bounds, density, and viewer or processing suitability |
| Sandbox | Non-production Zenodo environment used for safe validation/testing |
| Draft Record | Zenodo record not yet finalized/published |
| Batch Metadata | Per-file metadata extracted from MSF and persisted for batch processing |
| Global Hash Collision Warning | Advisory batch record-resolution warning shown when a non-exempt uploaded source file has the same SHA256 hash as a source file in an accessible WebHDP `.hdpc` inventory |
| Storage Mode | Operational policy for where files are kept/processed (`pure_cloud`, `cloud_backup`, `server_only`, `local`) |
