import re
import xml.etree.ElementTree as ET

from pathlib import Path


class DotNetAdapter:

    name = ".NET"

    PROJECT_EXTENSIONS = {
        ".csproj",
        ".fsproj",
        ".vbproj",
    }

    SOLUTION_EXTENSIONS = {
        ".sln",
        ".slnx",
    }

    def can_handle(self, file_path):
        path = Path(file_path)

        return (
            path.suffix.lower() in self.PROJECT_EXTENSIONS
            or path.suffix.lower() in self.SOLUTION_EXTENSIONS
        )

    def analyze_manifest(self, file_path):
        path = Path(file_path)

        if path.suffix.lower() in self.SOLUTION_EXTENSIONS:
            return self._analyze_solution(path)

        return self._analyze_project(path)

    def _empty_result(self, path):
        return {
            "ecosystem": ".NET",
            "file": str(path),
            "runtime": None,
            "sdk": None,
            "external": [],
            "local": [],
            "frameworks": [],
            "errors": [],
        }

    def _analyze_project(self, path):
        result = self._empty_result(path)

        try:
            tree = ET.parse(path)
            root = tree.getroot()

        except (ET.ParseError, OSError) as exc:
            result["errors"].append(str(exc))
            return result

        properties = self._read_properties(root)

        # Target framework
        frameworks = self._read_frameworks(properties)

        result["frameworks"] = frameworks

        if frameworks:
            result["runtime"] = frameworks[0]

        # SDK requirements, if declared in project properties
        result["sdk"] = properties.get("Sdk")

        # NuGet package references
        for element in root.iter():
            tag = self._tag_name(element.tag)

            if tag == "PackageReference":
                dependency = self._read_package_reference(
                    element
                )

                if dependency:
                    result["external"].append(dependency)

            elif tag == "ProjectReference":
                reference = element.attrib.get("Include")

                if reference:
                    result["local"].append({
                        "path": self._normalize_path(reference),
                        "type": "project_reference",
                    })

            elif tag == "Reference":
                # Traditional assembly reference.
                # This is not necessarily a NuGet package.
                include = element.attrib.get("Include")

                if include:
                    result["local"].append({
                        "path": include,
                        "type": "assembly_reference",
                    })

        # Remove duplicate package references.
        result["external"] = self._deduplicate(
            result["external"]
        )

        result["local"] = self._deduplicate(
            result["local"]
        )

        return result

    def _read_properties(self, root):
        properties = {}

        for element in root.iter():
            tag = self._tag_name(element.tag)

            if element.text:
                value = element.text.strip()

                if value:
                    properties[tag] = value

        # SDK-style project declaration:
        # <Project Sdk="Microsoft.NET.Sdk">
        sdk = root.attrib.get("Sdk")

        if sdk:
            properties["Sdk"] = sdk

        return properties

    def _read_frameworks(self, properties):
        frameworks = []

        target_framework = properties.get(
            "TargetFramework"
        )

        target_frameworks = properties.get(
            "TargetFrameworks"
        )

        if target_framework:
            frameworks.extend(
                self._split_frameworks(target_framework)
            )

        if target_frameworks:
            frameworks.extend(
                self._split_frameworks(target_frameworks)
            )

        # Preserve order and remove duplicates.
        return list(dict.fromkeys(frameworks))

    def _split_frameworks(self, value):
        return [
            item.strip()
            for item in value.split(";")
            if item.strip()
        ]

    def _read_package_reference(self, element):
        name = element.attrib.get("Include")

        if not name:
            name = element.attrib.get("Update")

        if not name:
            return None

        version = element.attrib.get("Version")

        # Also supports:
        # <PackageReference Include="Example.Package">
        #     <Version>1.2.3</Version>
        # </PackageReference>
        if not version:
            for child in element:
                if self._tag_name(child.tag) == "Version":
                    if child.text:
                        version = child.text.strip()

        # Preserve conditional references.
        condition = element.attrib.get("Condition")

        dependency = {
            "name": name.strip(),
            "version": version,
        }

        if condition:
            dependency["condition"] = condition

        return dependency

    def _analyze_solution(self, path):
        result = self._empty_result(path)

        try:
            text = path.read_text(
                encoding="utf-8-sig",
                errors="replace",
            )

        except OSError as exc:
            result["errors"].append(str(exc))
            return result

        if path.suffix.lower() == ".sln":
            result["local"] = self._parse_sln(text)

        elif path.suffix.lower() == ".slnx":
            result["local"] = self._parse_slnx(
                path,
                text,
                result,
            )

        return result

    def _parse_sln(self, text):
        projects = []

        # Example:
        # Project("{GUID}") = "API", "API\API.csproj", "{GUID}"
        pattern = re.compile(
            r'^Project\("[^"]+"\)\s*=\s*"([^"]+)",\s*"([^"]+)"',
            re.MULTILINE,
        )

        for match in pattern.finditer(text):
            name = match.group(1)
            project_path = self._normalize_path(
                match.group(2)
            )

            if project_path.lower().endswith(
                tuple(self.PROJECT_EXTENSIONS)
            ):
                projects.append({
                    "name": name,
                    "path": project_path,
                    "type": "solution_project",
                })

        return self._deduplicate(projects)

    def _parse_slnx(self, path, text, result):
        projects = []

        try:
            root = ET.fromstring(text)

        except ET.ParseError as exc:
            result["errors"].append(str(exc))
            return projects

        for element in root.iter():
            tag = self._tag_name(element.tag)

            if tag != "Project":
                continue

            project_path = (
                element.attrib.get("Path")
                or element.attrib.get("Include")
            )

            if not project_path:
                continue

            projects.append({
                "name": Path(project_path).stem,
                "path": self._normalize_path(project_path),
                "type": "solution_project",
            })

        return self._deduplicate(projects)

    @staticmethod
    def _tag_name(tag):
        # Handles XML namespaces.
        return tag.split("}")[-1]

    @staticmethod
    def _normalize_path(path):
        return str(path).replace("\\", "/")

    @staticmethod
    def _deduplicate(items):
        unique = []
        seen = set()

        for item in items:
            key = (
                item.get("name"),
                item.get("version"),
                item.get("path"),
                item.get("type"),
            )

            if key in seen:
                continue

            seen.add(key)
            unique.append(item)

        return unique