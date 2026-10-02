import xml.etree.ElementTree as ET
from pathlib import Path


class CSharpAdapter:

    name = "C#"

    def can_handle(self, file_path):
        return Path(file_path).suffix.lower() == ".csproj"

    def analyze_manifest(self, file_path):

        path = Path(file_path)

        result = {
            "ecosystem": "C#",
            "file": str(path),
            "runtime": None,
            "external": [],
            "local": []
        }

        try:
            tree = ET.parse(path)
            root = tree.getroot()

        except (
            ET.ParseError,
            OSError
        ):
            return result

        for element in root.iter():

            tag = element.tag.split("}")[-1]

            if tag == "TargetFramework":

                result["runtime"] = (
                    element.text.strip()
                    if element.text
                    else None
                )

            elif tag == "PackageReference":

                name = element.attrib.get("Include")

                version = element.attrib.get("Version")

                if name:
                    result["external"].append({
                        "name": name,
                        "version": version
                    })

            elif tag == "ProjectReference":

                reference = element.attrib.get("Include")

                if reference:
                    reference = reference.replace("\\", "/")

                    result["local"].append({
                        "path": reference
                    })

        return result
