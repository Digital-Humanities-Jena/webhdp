import json
import os
from datetime import datetime

VERSION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "version.json")

def bump_version():
    if not os.path.exists(VERSION_FILE):
        data = {"version": "0.1.0", "timestamp": ""}
    else:
        with open(VERSION_FILE, "r") as f:
            data = json.load(f)

    # Bump patch version
    version_parts = data["version"].split(".")
    if len(version_parts) == 3:
        version_parts[2] = str(int(version_parts[2]) + 1)
        data["version"] = ".".join(version_parts)

    # Update timestamp
    data["timestamp"] = datetime.now().isoformat()

    with open(VERSION_FILE, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Bumped version to {data['version']} with timestamp {data['timestamp']}")

if __name__ == "__main__":
    bump_version()
