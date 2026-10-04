import json
from pathlib import Path


class NodeAdapter:

    name = "Node.js"

    def can_handle(self, file_path):
        return Path(file_path).name == "package.json"

    def analyze_manifest(self, file_path):

        path = Path(file_path)

        result = {
            "ecosystem": "Node.js",
            "file": str(path),
            "runtime": None,
            "external": [],
            "local": []
        }

        try:
            data = json.loads(
                path.read_text(
                    encoding="utf-8",
                    errors="ignore"
                )
            )
        except (
            json.JSONDecodeError,
            OSError
        ):
            return result

        engines = data.get(
            "engines",
            {}
        )

        if "node" in engines:
            result["runtime"] = engines["node"]

        for section in [
            "dependencies",
            "devDependencies",
            "peerDependencies",
            "optionalDependencies"
        ]:

            packages = data.get(
                section,
                {}
            )

            for name, version in packages.items():

                result["external"].append({
                    "name": name,
                    "version": version
                })

        return result