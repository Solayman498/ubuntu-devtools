import re
from pathlib import Path


class PythonAdapter:

    name = "Python"

    def can_handle(self, file_path):
        return Path(file_path).name in {
            "requirements.txt",
            "pyproject.toml",
            "Pipfile",
            "setup.py",
        }

    def analyze_manifest(self, file_path):

        path = Path(file_path)

        result = {
            "ecosystem": "Python",
            "file": str(path),
            "runtime": None,
            "external": [],
            "local": []
        }

        try:

            if path.name == "requirements.txt":
                result["external"] = self._parse_requirements(path)

            elif path.name == "pyproject.toml":
                result["external"] = self._parse_pyproject(path)

            elif path.name == "Pipfile":
                result["external"] = self._parse_pipfile(path)

            elif path.name == "setup.py":
                result["external"] = self._parse_setup(path)

        except (OSError, ValueError):
            pass

        return result

    def _parse_requirements(self, path):

        dependencies = []

        for line in path.read_text(
            encoding="utf-8",
            errors="ignore"
        ).splitlines():

            line = line.strip()

            if not line:
                continue

            if line.startswith("#"):
                continue

            if line.startswith((
                "-r",
                "--requirement",
                "-e",
                "--editable",
                "--index-url",
                "--extra-index-url"
            )):
                continue

            match = re.match(
                r"^([A-Za-z0-9_.-]+)(\[[^\]]+\])?\s*(.*)$",
                line
            )

            if not match:
                continue

            name = match.group(1)
            extra = match.group(2)
            version = match.group(3).strip()

            if extra:
                name += extra

            dependencies.append({
                "name": name,
                "version": version or None
            })

        return dependencies

    def _parse_pyproject(self, path):

        try:
            import tomllib
        except ImportError:
            return []

        data = tomllib.loads(
            path.read_text(
                encoding="utf-8",
                errors="ignore"
            )
        )

        dependencies = []

        project = data.get("project", {})

        for dependency in project.get(
            "dependencies",
            []
        ):

            name, version = self._split_dependency(
                dependency
            )

            dependencies.append({
                "name": name,
                "version": version
            })

        return dependencies

    def _parse_pipfile(self, path):

        try:
            import tomllib
        except ImportError:
            return []

        data = tomllib.loads(
            path.read_text(
                encoding="utf-8",
                errors="ignore"
            )
        )

        dependencies = []

        for section in [
            "packages",
            "dev-packages"
        ]:

            packages = data.get(
                section,
                {}
            )

            for name, version in packages.items():

                dependencies.append({
                    "name": name,
                    "version": str(version)
                })

        return dependencies

    def _parse_setup(self, path):

        text = path.read_text(
            encoding="utf-8",
            errors="ignore"
        )

        dependencies = []

        match = re.search(
            r"install_requires\s*=\s*\[(.*?)\]",
            text,
            re.DOTALL
        )

        if not match:
            return dependencies

        content = match.group(1)

        for dependency in re.findall(
            r"['\"]([^'\"]+)['\"]",
            content
        ):

            name, version = self._split_dependency(
                dependency
            )

            dependencies.append({
                "name": name,
                "version": version
            })

        return dependencies

    def _split_dependency(self, dependency):

        match = re.match(
            r"^([A-Za-z0-9_.-]+)(\[[^\]]+\])?\s*(.*)$",
            dependency.strip()
        )

        if not match:
            return dependency.strip(), None

        name = match.group(1)
        extra = match.group(2)
        version = match.group(3).strip()

        if extra:
            name += extra

        return (
            name,
            version or None
        )