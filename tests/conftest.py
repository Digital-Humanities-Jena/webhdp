import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
root_str = os.fspath(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

os.environ.setdefault("ZENODO_SANDBOX_API_KEY", "pytest-sandbox-token")
os.environ.setdefault("ZENODO_API_KEY", "pytest-production-token")
