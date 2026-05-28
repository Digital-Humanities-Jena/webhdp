# EDM Primary Visual Selection Strategy

## Automated EDM Generation And File Selection

### 1. Abstract

Automated EDM generation cannot rely only on repository metadata. A Zenodo
record may be categorized as a dataset while its most useful presentation file
is a 3D model or a rendered image.

This note describes the selection rule used to choose the primary visual
resource for `edm:isShownBy`. The rule prefers detected file content over broad
record-level categories when the file list contains a clear visual asset.

---

### 2. Internal File Classes

Incoming files are mapped into internal classes regardless of the original
repository MIME type.

| Class | Priority Level | Description | File Extensions (Examples) |
| --- | --- | --- | --- |
| **`3d_model`** | **1 (Highest)** | Interactive, spatial content. | `.glb`, `.gltf`, `.obj`, `.ply`, `.stl`, `.usdz`, `.x3d` |
| **`image`** | **2** | Visual representation. | `.jpg`, `.jpeg`, `.png`, `.tiff`, `.webp` |
| **`video`** | **3** | Time-based media. | `.mp4`, `.mov`, `.webm` |
| **`document`** | **4** | Human-readable textual information. | `.pdf`, `.doc`, `.docx`, `.txt` |
| **`data`** | **5 (Lowest)** | Machine-readable data or auxiliary metadata. | `.xml`, `.json`, `.csv`, `.zip` |

---

### 3. Three-Phase Selection Logic

The selection of the primary file (`edm:isShownBy`) must follow a strict three-phase process.

#### Phase 1: File Identification

*Objective:* Correctly categorize files even when metadata is generic (e.g., `application/octet-stream`).

**Logic:**

1. **Check Extension:** The file extension is usually the strongest indicator
   of user intent.
* *Action:* Check `filename` against the configured extension registry,
  including formats such as `.usdz`.


2. **Check MIME Type:** Use as a validator or fallback.
* *Action:* If `mimetype` contains `model/` or `image/`, respect it.


3. **Heuristic Fallback:** If MIME is `application/octet-stream` and the
   extension is missing or unknown:
* *Action:* Scan `filename` for keywords like "scan", "model", "mesh".



#### Phase 2: Visual Asset Selection

*Objective:* Prevent record metadata (e.g., "Dataset") from suppressing visual content.

**Logic:**
First check whether the file list contains a usable visual asset. If it does,
prefer that asset class over the broader record type.

1. **Scan for `3d_model`:** Does the record contain *any* file identified as Class `3d_model`?
* **YES:** The Selection Pool is restricted to **`3d_model`** files. (The record is effectively treated as a 3D Object, ignoring the "Dataset" label).
* **NO:** Proceed to step 2.


2. **Scan for `image`:** Does the record contain *any* file identified as Class `image`?
* **YES:** The Selection Pool is restricted to **`image`** files.
* **NO:** Proceed to step 3.


3. **Fallback to Metadata Preference:**
* If no 3D or Image files exist, revert to the metadata type (e.g., if Record is "Text", prefer `document`; if "Software", prefer `data`).



#### Phase 3: Tie-Breaking

*Objective:* Select the "Master" file over "Thumbnails" or "Previews".

**Logic:**
When multiple files exist in the selected Class (e.g., multiple `.glb` files or multiple `.jpg`s):

1. **Sort by File Size (Descending):** Larger files generally correlate with higher resolution, polygon count, or information density.
2. **Select Top Candidate:** The largest file in the highest priority class becomes `edm:isShownBy`.

---

### 4. Implementation Specification

The following Python implementation is optimized for `codebase/app/services/edm_converter.py`.

#### A. Enhanced Configuration

Expand the extension list to cover the "Blind Spots" identified in the stress test (e.g., USDZ).

```python
# Expanded Registry
FILE_TYPE_BY_EXTENSION = {
    # 3D Formats (Web & Source)
    'glb': '3d_model', 'gltf': '3d_model', 'obj': '3d_model',
    'stl': '3d_model', 'ply': '3d_model', 'fbx': '3d_model',
    'dae': '3d_model', 'x3d': '3d_model', 'wrl': '3d_model',
    'usdz': '3d_model', 'usdc': '3d_model', 'blend': '3d_model',

    # Standard Images
    'jpg': 'image', 'jpeg': 'image', 'png': 'image',
    'tif': 'image', 'tiff': 'image', 'webp': 'image',

    # Documents
    'pdf': 'document', 'doc': 'document', 'docx': 'document'
}

```

#### B. The Content-Type Resolver

This function handles the `application/octet-stream` issue found in Zenodo.

```python
def _get_file_content_type(self, file_dict: dict) -> str:
    """
    Determines internal file class using Extension > MIME > Heuristic priority.
    """
    filename = file_dict.get('key') or file_dict.get('filename', '')
    ext = self._get_file_extension(filename)
    mimetype = file_dict.get('mimetype', '').lower()

    # 1. Extension Authority (Fastest & often most accurate for user uploads)
    if ext in FILE_TYPE_BY_EXTENSION:
        return FILE_TYPE_BY_EXTENSION[ext]

    # 2. MIME Authority
    if 'model/' in mimetype or 'x-world/' in mimetype: return '3d_model'
    if 'image/' in mimetype: return 'image'
    if 'video/' in mimetype: return 'video'
    if 'application/pdf' in mimetype: return 'document'

    # 3. Heuristic Fallback for generic binaries
    if 'octet-stream' in mimetype:
        lower_name = filename.lower()
        if any(x in lower_name for x in ['model', 'scan', 'mesh']):
            return '3d_model'

    return 'data' # Default fallback

```

#### C. Primary File Selection

This replaces rigid resource-type selection with the visual priority order.

```python
def _select_smart_primary_file(self, files: list, record_edm_type: str) -> dict:
    if not files:
        return None

    # Group files by their detected Content Class
    files_by_type = {}
    for f in files:
        c_type = self._get_file_content_type(f)
        files_by_type.setdefault(c_type, []).append(f)

    # DEFINITION OF VISUAL PRIORITY
    # This list enforces that Visuals > Text, regardless of record metadata.
    priority_order = ['3d_model', 'image', 'video', 'document', 'data']

    # EXECUTE SELECTION
    for c_type in priority_order:
        if c_type in files_by_type:
            candidates = files_by_type[c_type]

            # TIE-BREAKER: File Size
            # Sort descending to pick the highest quality asset (e.g. Master vs Thumb)
            # Use '0' default to prevent errors if size is missing
            candidates.sort(key=lambda x: x.get('size', 0), reverse=True)

            selected_file = candidates[0]

            # Log the override if it differs from metadata expectation
            if record_edm_type == 'TEXT' and c_type == '3d_model':
                print(f"Visual Override: Selected 3D Model in Text Record.")

            return selected_file

    # Fallback
    return files[0]

```

---

### 5. Case Study

Applying this strategy to a Zenodo test record:

1. **Input:**
* Metadata: `resource_type: dataset` (Implies Text/Data).
* Files: `bucket.glb` (70MB), `thumb.jpg` (50KB), `meta.xml`.


2. **Phase 1 (Identification):**
* `bucket.glb`: Extension `.glb` matches `3d_model`.
* `thumb.jpg`: Extension `.jpg` matches `image`.


3. **Phase 2 (Visual Asset Selection):**
* Algorithm checks `priority_order`.
* Is `3d_model` present? **YES**.
* System ignores the fact that `record_edm_type` was "Dataset".


4. **Phase 3 (Tie-Breaking):**
* The system selects the `.glb` file.


5. **Outcome:**
* **Generated EDM:** `<edm:isShownBy rdf:resource="...bucket.glb"/>`
* **Viewer result:** The selected file can be used by a 3D-capable viewer.



### 6. Conclusion

The rule makes primary-file selection less dependent on broad record metadata.
When a record contains a detected 3D model or image, WebHDP can choose that
visual asset for EDM presentation instead of hiding it behind a generic dataset
classification.
