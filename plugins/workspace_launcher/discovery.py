import os
from pathlib import Path

from plugins.workspace_launcher.detector import ProjectDetector
from core.project_registry import ProjectRegistry


class ProjectDiscovery:
    SKIP_DIRECTORIES = {
        "proc",
        "sys",
        "dev",
        "run",
        "tmp",
        "lost+found",
        "__pycache__",
        "venv",
        ".venv",
        "env",
        ".env",
        "node_modules",
        ".git",
        ".vscode",
        ".idea",
        ".cache",
        ".npm",
        ".yarn",
        "build",
        "dist",
        "target",
        "bin",
        "obj",
        "vendor",
    }

    # Exclude these only when scanning the entire "/" filesystem.
    FULL_SCAN_EXCLUDED_ROOTS = {
        "/proc",
        "/sys",
        "/dev",
        "/run",
        "/tmp",
        "/var",
        "/usr",
        "/snap",
        "/opt",
        "/lost+found",
    }

    def __init__(self):
        self.detector = ProjectDetector()
        self.registry = ProjectRegistry()

    def discover(self, root_path=None, mode="workspace"):
        """
        Discover projects without changing the registry.

        mode='workspace':
            Scan the user's home directory by default.

        mode='full':
            Scan the requested root. If the root is '/',
            exclude selected operating-system directories.
        """

        if root_path is None:
            if mode == "full":
                root_path = "/"
            else:
                root_path = str(Path.home())

        root = Path(root_path).expanduser()

        try:
            root = root.resolve(strict=True)
        except (OSError, RuntimeError):
            return []

        if not root.is_dir():
            return []

        ignored_paths = {
            Path(path).resolve()
            for path in self.registry.get_ignored_paths()
        }

        excluded_roots = set()

        if mode == "full" and root == Path("/"):
            excluded_roots = {
                Path(path)
                for path in self.FULL_SCAN_EXCLUDED_ROOTS
            }

        projects = []
        visited_paths = set()

        self._scan(
            directory=root,
            projects=projects,
            ignored_paths=ignored_paths,
            excluded_roots=excluded_roots,
            visited_paths=visited_paths,
            root=root,
        )

        return projects

    def discover_and_register(self, root_path=None, mode="workspace"):
        projects = self.discover(
            root_path=root_path,
            mode=mode,
        )

        # Avoid clearing the existing registry if a scan
        # unexpectedly returns no results.
        if projects:
            self.registry.register_projects(projects)

        return projects

    def _scan(
        self,
        directory,
        projects,
        ignored_paths,
        excluded_roots,
        visited_paths,
        root,
    ):
        try:
            resolved = directory.resolve(strict=True)
        except (OSError, RuntimeError):
            return

        if not resolved.is_dir():
            return

        # Prevent repeated scans of the same resolved directory.
        if resolved in visited_paths:
            return

        visited_paths.add(resolved)

        # Ignore a selected project and its entire subtree.
        if any(
            resolved == ignored or ignored in resolved.parents
            for ignored in ignored_paths
        ):
            return

        # Skip excluded system roots and their descendants.
        if any(
            resolved == excluded or excluded in resolved.parents
            for excluded in excluded_roots
        ):
            return

        # Skip known non-project directories.
        if (
            resolved != root
            and resolved.name in self.SKIP_DIRECTORIES
        ):
            return

        try:
            result = self.detector.detect(str(resolved))
        except (OSError, PermissionError):
            result = None

        if result and result.get("type") != "Unknown":
            projects.append({
                "name": resolved.name or str(resolved),
                "path": str(resolved),
                "type": result["type"],
                "confidence": result.get("confidence", "Medium"),
                "files": result.get("files", []),
            })

            # A detected project is treated as one project.
            # Do not scan every folder inside it as another project.
            return

        try:
            with os.scandir(resolved) as entries:
                children = [
                    Path(entry.path)
                    for entry in entries
                    if entry.is_dir(follow_symlinks=False)
                ]
        except (OSError, PermissionError):
            return

        for child in children:
            self._scan(
                directory=child,
                projects=projects,
                ignored_paths=ignored_paths,
                excluded_roots=excluded_roots,
                visited_paths=visited_paths,
                root=root,
            )