from pathlib import Path
import subprocess
import sys

from plugins.workspace_launcher.discovery import ProjectDiscovery
from plugins.workspace_launcher.analyzer import DependencyAnalyzer


class WorkspaceAnalyzer:

    def __init__(self):
        self.discovery = ProjectDiscovery()
        self.analyzer = DependencyAnalyzer()

    def analyze_registered_projects(self, root_path="/home"):

        projects = self.discovery.discover_and_register(root_path)

        results = []

        for project in projects:

            dependencies = self.analyzer.resolve_dependencies(
                project["path"]
            )

            results.append({
                "name": project["name"],
                "path": project["path"],
                "type": project["type"],
                "confidence": project["confidence"],
                "dependencies": dependencies
            })

        return results

    def setup_and_launch(self, project):

        project_path = Path(project["path"])

        # Check project
        if not project_path.exists():
            return {
                "success": False,
                "status": "Project Not Found"
            }

        # Currently Python
        if project["type"] != "Python":
            return {
                "success": False,
                "status": "Only Python projects are supported currently"
            }

        # -------------------------------------------------
        # 1. Find or create virtual environment
        # -------------------------------------------------

        venv = project_path / ".venv"

        if not venv.exists():
            venv = project_path / "venv"

        if not venv.exists():

            print("Creating virtual environment...")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "venv",
                    str(project_path / ".venv")
                ],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:

                return {
                    "success": False,
                    "status": "Environment Creation Failed",
                    "error": result.stderr
                }

            venv = project_path / ".venv"

        python = venv / "bin" / "python"
        pip = venv / "bin" / "pip"

        if not python.exists() or not pip.exists():

            return {
                "success": False,
                "status": "Python Environment Invalid"
            }

        # -------------------------------------------------
        # 2. Detect dependencies
        # -------------------------------------------------

        print("Analyzing dependencies...")

        dependencies = self.analyzer.resolve_dependencies(
            str(project_path)
        )

        packages = []

        for dependency in dependencies:

            classification = dependency.get(
                "classification"
            )

            if classification not in {
                "declared_external",
                "undeclared_external"
            }:
                continue

            name = dependency.get("name")

            if name and name not in packages:
                packages.append(name)

        print("Dependencies:", packages)

        # -------------------------------------------------
        # 3. Install normal dependencies
        # -------------------------------------------------

        normal_packages = [
            package
            for package in packages
            if package.lower() != "torch"
        ]

        if normal_packages:

            print("Installing:", normal_packages)

            result = subprocess.run(
                [
                    str(pip),
                    "install",
                    *normal_packages
                ],
                cwd=str(project_path)
            )

            if result.returncode != 0:

                return {
                    "success": False,
                    "status": "Dependency Installation Failed"
                }

        # -------------------------------------------------
        # 4. Install CPU-only PyTorch
        # -------------------------------------------------

        if "torch" in packages:

            print("Installing CPU-only PyTorch...")

            result = subprocess.run(
                [
                    str(pip),
                    "install",
                    "torch",
                    "--index-url",
                    "https://download.pytorch.org/whl/cpu"
                ],
                cwd=str(project_path)
            )

            if result.returncode != 0:

                return {
                    "success": False,
                    "status": "PyTorch Installation Failed"
                }

        # -------------------------------------------------
        # 5. Find project entry file
        # -------------------------------------------------

        entry_file = self.find_entry_file(
            project_path
        )

        if not entry_file:

            return {
                "success": False,
                "status": "Python Entry File Not Found"
            }

        # -------------------------------------------------
        # 6. Launch project
        # -------------------------------------------------

        print(
            f"Launching: {entry_file}"
        )

        try:

            process = subprocess.Popen(
                [
                    str(python),
                    str(entry_file)
                ],
                cwd=str(project_path)
            )

        except OSError as error:

            return {
                "success": False,
                "status": "Launch Failed",
                "error": str(error)
            }

        return {
            "success": True,
            "status": "Project Launched",
            "pid": process.pid,
            "entry_file": str(entry_file),
            "dependencies": packages
        }

    def find_entry_file(self, project_path):

        preferred_files = [
            "main.py",
            "app.py",
            "server.py",
            "run.py"
        ]

        ignored = {
            ".venv",
            "venv",
            "env",
            "node_modules",
            "__pycache__",
            ".git"
        }

        for filename in preferred_files:

            for file in project_path.rglob(filename):

                if any(
                    part in ignored
                    for part in file.parts
                ):
                    continue

                return file

        return None