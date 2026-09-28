from pathlib import Path

from plugins.workspace_launcher.detector import ProjectDetector
from core.project_registry import ProjectRegistry


class ProjectDiscovery:

    def __init__(self):
        self.detector = ProjectDetector()
        self.registry = ProjectRegistry()

        self.skip_directories = {
            "proc",
            "sys",
            "dev",
            "run",
            "tmp",
            "lost+found",
            "__pycache__",
            "node_modules",
            ".git",
            ".vscode",
            ".idea",
            ".cache",
            ".config",
            ".local",
            ".npm",
            ".yarn",
            "venv",
            ".venv",
        }

    def discover(self, root_path="/"):
        root = Path(root_path)

        if not root.exists() or not root.is_dir():
            return []

        projects = []
        self._scan(root, projects)

        return projects

    def discover_and_register(self, root_path="/"):
        projects = self.discover(root_path)

        self.registry.register_projects(projects)

        return projects

    def _scan(self, directory, projects):

        if directory.name in self.skip_directories:
            return

        try:
            result = self.detector.detect(str(directory))
        except (PermissionError, OSError):
            result = None

        if result and result["type"] != "Unknown":

            project = {
                "name": directory.name,
                "path": str(directory),
                "type": result["type"],
                "confidence": result["confidence"],
                "files": result["files"],
            }

            if self._is_project_root(directory, result):

                projects.append(project)

                return

        try:
            children = list(directory.iterdir())
        except (PermissionError, OSError):
            return

        for child in children:

            if not child.is_dir():
                continue

            if child.name in self.skip_directories:
                continue

            if child.is_symlink():
                continue

            self._scan(child, projects)

    def _is_project_root(self, directory, result):

        try:
            children = list(directory.iterdir())
        except (PermissionError, OSError):
            return False

        files = {
            child.name
            for child in children
            if child.is_file()
        }

        folders = {
            child.name
            for child in children
            if child.is_dir()
        }

        strong_markers = {
            "requirements.txt",
            "pyproject.toml",
            "Pipfile",
            "setup.py",
            "package.json",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "CMakeLists.txt",
            "Makefile",
            "composer.json",
            "Cargo.toml",
            "go.mod",
            "Gemfile",
            "pubspec.yaml",
            "Dockerfile",
        }

        if files & strong_markers:
            return True

        if "run.bat" in files or "run.sh" in files:
            return True

        if "frontend" in folders and "backend" in folders:
            return True

        source_extensions = {
            ".py",
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
            ".java",
            ".c",
            ".cpp",
            ".cc",
            ".cs",
            ".php",
            ".rs",
            ".go",
            ".rb",
            ".dart",
        }

        for child in children:

            if child.is_file() and child.suffix in source_extensions:
                return True

        return False