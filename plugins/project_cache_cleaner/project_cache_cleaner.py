import os
import shutil
from pathlib import Path


class ProjectCacheCleaner:

    def __init__(self):
        self.name = "Project Cache Cleaner"

        # Safe cache directories
        self.cache_rules = {
            # Python
            "__pycache__": {
                "category": "Python",
                "type": "Standard"
            },
            ".pytest_cache": {
                "category": "Python",
                "type": "Standard"
            },
            ".mypy_cache": {
                "category": "Python",
                "type": "Standard"
            },
            ".ruff_cache": {
                "category": "Python",
                "type": "Standard"
            },

            # .NET
            "bin": {
                "category": ".NET Build Output",
                "type": "Optional"
            },
            "obj": {
                "category": ".NET Build Output",
                "type": "Optional"
            },

            # Node.js
            ".npm": {
                "category": "Node.js",
                "type": "Optional"
            },
            ".yarn": {
                "category": "Node.js",
                "type": "Optional"
            },
            "node_modules": {
                "category": "Node.js",
                "type": "Optional"
            },

            # Java
            ".gradle": {
                "category": "Java / Gradle",
                "type": "Optional"
            },
            "target": {
                "category": "Java / Build Output",
                "type": "Optional"
            },

            # General
            ".cache": {
                "category": "General",
                "type": "Optional"
            },
            "build": {
                "category": "Build Output",
                "type": "Optional"
            },
            "dist": {
                "category": "Build Output",
                "type": "Optional"
            },

            # Python Environments
            ".venv": {
                "category": "Python Environment",
                "type": "Optional"
            },
            "venv": {
                "category": "Python Environment",
                "type": "Optional"
            },
            "env": {
                "category": "Python Environment",
                "type": "Optional"
            },
            ".tox": {
                "category": "Python Environment",
                "type": "Optional"
            }
        }

        # Directories that should never be scanned internally
        self.ignored_directories = {
            ".git",
            ".svn"
        }

    def get_name(self):
        return self.name

    # --------------------------------------------------
    # Calculate Directory Size
    # --------------------------------------------------

    def calculate_folder_size(self, folder_path):

        folder_path = Path(folder_path)

        if not folder_path.is_dir() or folder_path.is_symlink():
            return 0

        total_size = 0

        for current_path, directories, files in os.walk(
            folder_path,
            topdown=True,
            followlinks=False
        ):

            directories[:] = [
                directory
                for directory in directories
                if not (Path(current_path) / directory).is_symlink()
            ]

            for filename in files:

                file_path = Path(current_path) / filename

                try:
                    if file_path.is_symlink():
                        continue

                    total_size += file_path.stat().st_size

                except (OSError, PermissionError):
                    continue

        return total_size

    # --------------------------------------------------
    # Format File Size
    # --------------------------------------------------

    @staticmethod
    def format_size(size):

        units = ["B", "KB", "MB", "GB", "TB"]

        size = float(size)

        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.2f} {unit}"

            size /= 1024

    # --------------------------------------------------
    # Scan Project
    # --------------------------------------------------

    def scan_project(self, project_path):

        root = Path(project_path).expanduser().resolve()

        if not root.exists():
            raise FileNotFoundError(
                f"Project directory does not exist: {root}"
            )

        if not root.is_dir():
            raise NotADirectoryError(
                f"Not a directory: {root}"
            )

        results = []

        for current_path, directories, files in os.walk(
            root,
            topdown=True,
            followlinks=False
        ):

            current = Path(current_path)

            directories[:] = [
                directory
                for directory in directories
                if directory not in self.ignored_directories
                and not (current / directory).is_symlink()
            ]

            detected = []

            for directory in directories:

                rule = self.cache_rules.get(directory)

                if not rule:
                    continue

                folder_path = current / directory

                detected.append((folder_path, rule))

            # Detect candidates at this directory level
            for folder_path, rule in detected:

                size = self.calculate_folder_size(folder_path)

                if size <= 0:
                    continue

                results.append({
                    "name": folder_path.name,
                    "path": str(folder_path),
                    "size": size,
                    "formatted_size": self.format_size(size),
                    "category": rule["category"],
                    "type": rule["type"]
                })

            # Do not scan inside detected folders.
            # This prevents duplicate size counting.
            detected_paths = {
                folder_path.name
                for folder_path, rule in detected
            }

            directories[:] = [
                directory
                for directory in directories
                if directory not in detected_paths
            ]

        return sorted(
            results,
            key=lambda item: item["size"],
            reverse=True
        )

    # --------------------------------------------------
    # Clean Selected Folders
    # --------------------------------------------------

    def clean_selected(self, project_path, selected_paths):

        root = Path(project_path).expanduser().resolve()

        if not root.is_dir():
            raise NotADirectoryError(
                f"Invalid project directory: {root}"
            )

        results = []

        for selected_path in selected_paths:

            folder = Path(selected_path).expanduser()

            try:
                # Do not allow deleting symbolic links
                if folder.is_symlink():
                    raise ValueError(
                        "Symbolic links cannot be cleaned."
                    )

                folder = folder.resolve(strict=True)

                # Folder must be inside the selected project
                if not folder.is_relative_to(root):
                    raise ValueError(
                        "Selected folder is outside the project."
                    )

                if folder == root:
                    raise ValueError(
                        "Project root cannot be deleted."
                    )

                if not folder.is_dir():
                    raise ValueError(
                        "Selected path is not a directory."
                    )

                # Only allow recognized cache directories
                if folder.name not in self.cache_rules:
                    raise ValueError(
                        "This directory is not an approved cleanup target."
                    )

                size = self.calculate_folder_size(folder)

                shutil.rmtree(folder)

                results.append({
                    "path": str(folder),
                    "success": True,
                    "freed_size": size,
                    "message": "Cleaned successfully"
                })

            except Exception as error:

                results.append({
                    "path": str(selected_path),
                    "success": False,
                    "freed_size": 0,
                    "message": str(error)
                })

        return results

    # --------------------------------------------------
    # Refresh Scan
    # --------------------------------------------------

    def refresh(self, project_path):
        return self.scan_project(project_path)