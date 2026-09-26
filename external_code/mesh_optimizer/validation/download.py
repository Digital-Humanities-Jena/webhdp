"""Download the pinned public validation corpus and its per-model license notes."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    sources = json.loads(Path(__file__).with_name('sources.json').read_text())
    inputs = args.directory / 'inputs'; inputs.mkdir(parents=True, exist_ok=True)
    licenses = args.directory / 'licenses'; licenses.mkdir(exist_ok=True)
    for model in sources['models']:
        target = inputs / (model['name'] + '.glb')
        data = target.read_bytes() if target.exists() else urlopen(model['url'], timeout=60).read()
        if hashlib.sha256(data).hexdigest() != model['sha256']:
            raise ValueError(f"Checksum mismatch for {model['name']}")
        target.write_bytes(data)
        url = model['url'].rsplit('/glTF-Binary/', 1)[0] + '/README.md'
        (licenses / (model['name'] + '.md')).write_bytes(urlopen(url, timeout=60).read())
        print(model['name'], len(data))
    (args.directory / 'sources.json').write_text(json.dumps(sources, indent=2))


if __name__ == '__main__':
    main()
