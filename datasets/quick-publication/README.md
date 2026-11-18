# Quick 3D Publication sample data

These original models are synthetic training assets representing familiar
cultural heritage objects. Digital Humanities Jena provides the model geometry,
textures and preview images under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).

| Sample | ZIP structure | What preparation demonstrates |
| --- | --- | --- |
| Terracotta Vessel | An OBJ and MTL in a nested export directory with a texture subfolder | Preserves a complete dependency tree |
| Painted Floor Tile | A glTF with sibling binary buffer and texture directories | Corrects a transposed letter in the texture reference |
| Bronze Seal | OBJ and MTL at the ZIP root | Omits a missing map and uses the existing bronze material |
| Glazed Bowl | Root-level OBJ and MTL with surface and detail folders | Relinks the moved glaze image and omits a truncated optional detail map |

Each ZIP contains a WebHDP-compatible `metadata.csv` that links one metadata
row to the exact relative model path. Upload a ZIP as downloaded to preserve its
path structure. The sample source archives intentionally retain the repair
scenarios. The Bronze Seal texture is absent and the Glazed Bowl detail PNG is deliberately truncated. The bowl retains its original, usable glaze texture. All ZIP containers and model geometry are valid.

Run `python datasets/quick-publication/build_samples.py` from the repository
root with Pillow installed to regenerate the archives and the preview images
from the same synthetic geometry.
