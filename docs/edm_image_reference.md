# EDM Image Referencing Mechanism

This document explains how the HDP pipeline references generated 2D previews (renders) in the Europeana Data Model (EDM) XML.

## Overview

When a 3D model is ingested, the `Fast Renderer` service generates a set of 2D preview images (e.g., `model_r000.png` ... `model_r330.png`). These images are referenced in the EDM XML as the visual representation (`edm:object` / thumbnail) for the 3D object.

## Metadata Flow

1.  **Rendering**: The `fast-renderer` service runs and outputs image files to a local directory within the session.
2.  **Registration**: The pipeline (`pipeline_routes.py`) detects these generated files and registers them in the HDP database as source files for the project.
3.  **Context Injection**:
    When `EdmService.generate_edm_xml` is called, the pipeline explicitly collects the list of generated render files (which are not yet in the Zenodo draft metadata) and passes them as `additional_files`.
4.  **Template Logic**:
    *   `EdmService` normalizes these additional files into the file list.
    *   `_select_thumbnail_file` scans the file list for images. It prioritizes files with "thumb" or "preview" in the name, or falls back to size/alphabetical order.
    *   The selected file is assigned to the `thumbnail_file` variable in the Jinja2 context.
5.  **XML Generation**:
    The EDM template renders the `edm:object` property using the predicted Zenodo Content URL of the selected thumbnail file.

    ```xml
    <edm:object rdf:resource="https://zenodo.org/api/records/{record_id}/files/{filename}/content"/>
    ```

## Logic Details

### File Selection (`EdmService._select_thumbnail_file`)
- **Filter**: Considers files with `content_type` = `image`.
- **Scoring**:
    - `+20` if filename contains "thumb"
    - `+15` if filename matches Fast Renderer pattern (`_r\d{3}.png`)
        - `+2` bonus if it matches a preferred angle (e.g. `r029`)
    - `+10` if filename contains "preview"
    - `-5` if it matches the main file (strongly avoid using the main object as its own thumbnail).
- **Sort**: Score (descending), Size (descending).

### URL Prediction
Since the files are uploaded to Zenodo *after* EDM generation (because the EDM file itself must be part of the upload), the URLs are predicted based on the deterministic Zenodo API file content endpoint structure.
