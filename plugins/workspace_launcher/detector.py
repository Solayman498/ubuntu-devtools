from pathlib import Path


class ProjectDetector:
    """Detect projects using root-level project markers."""

    PYTHON_MARKERS = {
        "requirements.txt",
        "pyproject.toml",
        "Pipfile",
        "setup.py",
        "setup.cfg",
    }

    PROJECT_MARKERS = {
        # JavaScript / TypeScript
        "package.json",

        # Java
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",

        # C / C++
        "CMakeLists.txt",
        "Makefile",

        # PHP
        "composer.json",

        # Rust
        "Cargo.toml",

        # Go
        "go.mod",
        "go.work",

        # Ruby
        "Gemfile",

        # Flutter / Dart
        "pubspec.yaml",

        # Docker
        "Dockerfile",
        "docker-compose.yml",
        "compose.yaml",

        # Swift
        "Package.swift",
    }

    PROJECT_EXTENSIONS = {
        ".csproj",
        ".fsproj",
        ".vbproj",
        ".sln",
        ".slnx",
    }

    SOURCE_EXTENSIONS = {
        ".py", ".js", ".jsx", ".ts", ".tsx",
        ".java", ".kt", ".c", ".h", ".cpp", ".hpp",
        ".cs", ".php", ".rs", ".go", ".rb", ".dart",
        ".swift",
    }

    def detect(self, project_path):
        path = Path(project_path)

        if not path.is_dir() or path.is_symlink():
            return self._unknown()

        try:
            with __import__("os").scandir(path) as entries:
                children = list(entries)
        except (PermissionError, OSError):
            return self._unknown()

        files = set()
        directories = set()

        for entry in children:
            try:
                if entry.is_file(follow_symlinks=False):
                    files.add(entry.name)
                elif entry.is_dir(follow_symlinks=False):
                    directories.add(entry.name)
            except OSError:
                continue

        detected = set()
        detected.update(files.intersection(self.PYTHON_MARKERS))
        detected.update(files.intersection(self.PROJECT_MARKERS))

        for filename in files:
            if Path(filename).suffix.lower() in self.PROJECT_EXTENSIONS:
                detected.add(filename)

        # A frontend/backend layout is useful supporting evidence.
        has_frontend_backend = (
            "frontend" in directories and "backend" in directories
        )

        if has_frontend_backend:
            detected.update({"frontend/", "backend/"})

        # Strong project markers are enough to identify a project.
        if detected:
            project_type = self._identify_type(files, directories)

            if project_type == "Unknown":
                project_type = "Project"

            return {
                "type": project_type,
                "confidence": "High",
                "files": sorted(detected),
            }

        # A Git directory alone is not enough.
        # README + source code provides weaker evidence of a repository.
        has_readme = any(
            name.lower().startswith("readme")
            for name in files
        )
        has_source = any(
            Path(name).suffix.lower() in self.SOURCE_EXTENSIONS
            for name in files
        )

        if ".git" in directories and (has_readme or has_source):
            return {
                "type": "Git Project",
                "confidence": "Medium",
                "files": [".git"] + (
                    ["README"] if has_readme else []
                ),
            }

        return self._unknown()

    def _identify_type(self, files, directories):
        if "frontend" in directories and "backend" in directories:
            return "Full-Stack"

        if files.intersection(self.PYTHON_MARKERS):
            return "Python"

        if "package.json" in files:
            return "Node.js"

        if "pom.xml" in files:
            return "Java / Maven"

        if {"build.gradle", "build.gradle.kts"}.intersection(files):
            return "Java / Gradle"

        if any(
            Path(name).suffix.lower() in self.PROJECT_EXTENSIONS
            for name in files
        ):
            return "C# / .NET"

        if "composer.json" in files:
            return "PHP"

        if "Cargo.toml" in files:
            return "Rust"

        if {"go.mod", "go.work"}.intersection(files):
            return "Go"

        if "Gemfile" in files:
            return "Ruby"

        if "pubspec.yaml" in files:
            return "Flutter / Dart"

        if "CMakeLists.txt" in files or "Makefile" in files:
            return "C / C++"

        if {
            "Dockerfile",
            "docker-compose.yml",
            "compose.yaml",
        }.intersection(files):
            return "Docker"

        if "Package.swift" in files:
            return "Swift"

        return "Unknown"

    @staticmethod
    def _unknown():
        return {
            "type": "Unknown",
            "confidence": "None",
            "files": [],
        }