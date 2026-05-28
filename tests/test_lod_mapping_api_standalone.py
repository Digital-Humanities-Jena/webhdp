import requests
import json
import yaml

BASE_URL = "http://localhost:8080/api/v1"
AUTH_URL = f"{BASE_URL}/auth/login"
EXPORT_URL = f"{BASE_URL}/edm/mapping/export"
IMPORT_URL = f"{BASE_URL}/edm/mapping/import"

USERNAME = "admin@hdp.com"
PASSWORD = "test123+#"

def get_token():
    try:
        resp = requests.post(AUTH_URL, json={"email": USERNAME, "password": PASSWORD})
        resp.raise_for_status()
        return resp.json()["data"]["access_token"]
    except Exception as e:
        print(f"Login failed: {e}")
        if 'resp' in locals():
            print(resp.text)
        return None

def test_export(token):
    print("\n--- Testing Export ---")
    headers = {"Authorization": f"Bearer {token}"}

    # Payload matching MappingConfig structure
    payload = {
        "zenodo": {
            "3d": {
                "zenodo:title": {"source": "msf", "field": "Title_Column", "value": ""},
                "zenodo:upload_type": {"source": "options", "field": "", "value": "dataset"}
            }
        },
        "edm": {
            "3d": {
                "dc:title": {"source": "msf", "field": "Title_Column", "value": ""}
            }
        },
        "iiif": {},
        "mets": {}
    }

    try:
        resp = requests.post(EXPORT_URL, json=payload, headers=headers)
        if resp.status_code == 200:
            content = resp.content.decode('utf-8')
            print("Export Success!")
            print("Received YAML content:")
            print(content)

            # Verify it is valid YAML
            y = yaml.safe_load(content)
            return content
        else:
            print(f"Export Failed: {resp.status_code}")
            print(resp.text)
            return None
    except Exception as e:
        print(f"Export Error: {e}")
        return None

def test_import(token, yaml_content):
    print("\n--- Testing Import (Valid) ---")
    headers = {"Authorization": f"Bearer {token}"}

    files = {
        'file': ('mapping.yaml', yaml_content, 'application/x-yaml')
    }

    try:
        resp = requests.post(IMPORT_URL, files=files, headers=headers)
        if resp.status_code == 200:
            print("Import Success!")
            print("Response:", resp.json())
        else:
            print(f"Import Failed: {resp.status_code}")
            print(resp.text)
    except Exception as e:
        print(f"Import Error: {e}")

def test_import_invalid(token):
    print("\n--- Testing Import (Invalid YAML) ---")
    headers = {"Authorization": f"Bearer {token}"}

    invalid_yaml = "edm: [this is not valid dictionary structure for our schema"
    files = {
        'file': ('invalid.yaml', invalid_yaml, 'application/x-yaml')
    }

    try:
        resp = requests.post(IMPORT_URL, files=files, headers=headers)
        print(f"Status Code: {resp.status_code}")
        print("Response:", resp.text)
        if resp.status_code == 400 or resp.status_code == 422:
             print("Correctly rejected.")
        else:
             print("Unexpected success or error.")

    except Exception as e:
        print(f"Import Invalid Error: {e}")

def test_import_schema_violation(token):
    print("\n--- Testing Import (Schema Violation) ---")
    headers = {"Authorization": f"Bearer {token}"}

    # Valid YAML but invalid schema (missing 'source' field in mapping item)
    invalid_schema = """
edm:
  3d:
    dc:title:
      field: Title_Column
"""
    files = {
        'file': ('violation.yaml', invalid_schema, 'application/x-yaml')
    }

    try:
        resp = requests.post(IMPORT_URL, files=files, headers=headers)
        print(f"Status Code: {resp.status_code}")
        print("Response:", resp.text)
         # Should be 422 Unprocessable Entity or 400 Bad Request
    except Exception as e:
        print(f"Schema Violation Error: {e}")

if __name__ == "__main__":
    token = get_token()
    if token:
        yaml_content = test_export(token)
        if yaml_content:
            test_import(token, yaml_content)
        test_import_invalid(token)
        test_import_schema_violation(token)
