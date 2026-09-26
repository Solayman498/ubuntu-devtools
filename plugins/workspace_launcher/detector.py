from pathlib import Path


class ProjectDetector:

    def detect(self, project_path):
        project_path = Path(project_path)

        if not project_path.exists():
            return {
                "type": "Unknown",
                "confidence": "None",
                "files": []
            }

        if not project_path.is_dir():
            return {
                "type": "Unknown",
                "confidence": "None",
                "files": []
            }

        detected_files = []

        # Search project up to 3 levels deep
        for path in project_path.rglob("*"):

            if not path.is_file():
                continue

            try:
                relative_path = path.relative_to(project_path)
            except ValueError:
                continue

            if len(relative_path.parts) > 3:
                continue

            name = path.name

            # Python
            if name in {
                "requirements.txt",
                "pyproject.toml",
                "Pipfile",
                "setup.py"
            }:
                detected_files.append(str(relative_path))

            elif path.suffix == ".py":
                detected_files.append(str(relative_path))

            # Node.js
            elif name in {
                "package.json",
                "package-lock.json",
                "yarn.lock",
                "pnpm-lock.yaml"
            }:
                detected_files.append(str(relative_path))

            # Java
            elif name in {
                "pom.xml",
                "build.gradle",
                "build.gradle.kts"
            }:
                detected_files.append(str(relative_path))

            # C / C++
            elif name in {
                "CMakeLists.txt",
                "Makefile"
            }:
                detected_files.append(str(relative_path))

            elif path.suffix in {".c", ".cpp", ".cc", ".h", ".hpp"}:
                detected_files.append(str(relative_path))

            # C# / .NET
            elif path.suffix in {".csproj", ".sln"}:
                detected_files.append(str(relative_path))

            # PHP
            elif name == "composer.json":
                detected_files.append(str(relative_path))

            elif path.suffix == ".php":
                detected_files.append(str(relative_path))

            # Rust
            elif name == "Cargo.toml":
                detected_files.append(str(relative_path))

            # Go
            elif name == "go.mod":
                detected_files.append(str(relative_path))

            elif path.suffix == ".go":
                detected_files.append(str(relative_path))

            # Ruby
            elif name == "Gemfile":
                detected_files.append(str(relative_path))

            elif path.suffix == ".rb":
                detected_files.append(str(relative_path))

            # Flutter / Dart
            elif name == "pubspec.yaml":
                detected_files.append(str(relative_path))

            elif path.suffix == ".dart":
                detected_files.append(str(relative_path))

            # Docker
            elif name in {
                "Dockerfile",
                "compose.yaml",
                "docker-compose.yml"
            }:
                detected_files.append(str(relative_path))

            # Git
            elif name == ".git":
                detected_files.append(str(relative_path))

            # Windows launch script
            elif path.suffix == ".bat":
                detected_files.append(str(relative_path))

            # Linux shell script
            elif path.suffix == ".sh":
                detected_files.append(str(relative_path))

        # Remove duplicates
        detected_files = sorted(set(detected_files))

        project_type = self._identify_type(
            detected_files
        )

        return {
            "type": project_type,
            "confidence": (
                "High"
                if project_type != "Unknown"
                else "None"
            ),
            "files": detected_files
        }

    def _identify_type(self, files):

        file_names = [
            Path(file).name
            for file in files
        ]

        # Strong dependency/configuration indicators first

        if "requirements.txt" in file_names:
            return "Python"

        if "pyproject.toml" in file_names:
            return "Python"

        if "package.json" in file_names:
            return "Node.js"

        if "pom.xml" in file_names:
            return "Java"

        if (
            "build.gradle" in file_names
            or "build.gradle.kts" in file_names
        ):
            return "Java / Gradle"

        if (
            "*.csproj" in files
            or "*.sln" in files
            or any(
                file.endswith(".csproj")
                or file.endswith(".sln")
                for file in files
            )
        ):
            return "C# / .NET"

        if "composer.json" in file_names:
            return "PHP"

        if "Cargo.toml" in file_names:
            return "Rust"

        if "go.mod" in file_names:
            return "Go"

        if "Gemfile" in file_names:
            return "Ruby"

        if "pubspec.yaml" in file_names:
            return "Flutter / Dart"

        # Source-code based detection

        if any(
            file.endswith(".py")
            for file in files
        ):
            return "Python"

        if any(
            file.endswith((".c", ".cpp", ".cc"))
            for file in files
        ):
            return "C / C++"

        if any(
            file.endswith(".cs")
            for file in files
        ):
            return "C# / .NET"

        if any(
            file.endswith(".php")
            for file in files
        ):
            return "PHP"

        if any(
            file.endswith(".rs")
            for file in files
        ):
            return "Rust"

        if any(
            file.endswith(".go")
            for file in files
        ):
            return "Go"

        if any(
            file.endswith(".rb")
            for file in files
        ):
            return "Ruby"

        if any(
            file.endswith(".dart")
            for file in files
        ):
            return "Flutter / Dart"

        return "Unknown"