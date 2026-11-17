#!/usr/bin/env python3
"""Inspect the actual contained CUDA runtime loaded by Torch and COLMAP."""
import ctypes
import json
from pathlib import Path
import torch
import pycolmap

loaded = sorted({line.split()[-1] for line in Path("/proc/self/maps").read_text().splitlines()
                 if "libcudart.so" in line})
assert loaded
results = []
for path in loaded:
    library = ctypes.CDLL(path)
    version = ctypes.c_int()
    code = library.cudaRuntimeGetVersion(ctypes.byref(version))
    results.append({"path": path, "runtime_version": version.value, "version_query_code": code,
                    "exports_cudaLibraryGetKernel": hasattr(library, "cudaLibraryGetKernel")})
print(json.dumps({"scope": "Actual contained loaded-library inspection; no model inference",
                  "torch_version": torch.__version__, "torch_cuda_version": torch.version.cuda,
                  "pycolmap_version": pycolmap.__version__, "loaded_cudart": results}))
