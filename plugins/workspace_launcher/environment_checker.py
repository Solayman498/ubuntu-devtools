import json
import re
import subprocess
import sys

from pathlib import Path


class EnvironmentChecker:
    """
    Discover Python environments and verify project dependencies.

    Supported virtual environments:
    - .venv/
    - venv/
    - env/
    - Nested environments such as backend/.venv/

    Supported dependency manifests:
    - requirements.txt
    - requirements-dev.txt
    - pyproject.toml
    - Pipfile
    - Pipfile.lock
    - poetry.lock
    - uv.lock
    - environment.yml
    - environment.yaml

    This module never installs packages or modifies projects.
    """

    ENVIRONMENT_DIRECTORIES = (
        ".venv",
        "venv",
        "env",
    )

    MANIFEST_NAMES = (
        "requirements.txt",
        "requirements-dev.txt",
        "pyproject.toml",
        "Pipfile",
        "Pipfile.lock",
        "poetry.lock",
        "uv.lock",
        "environment.yml",
        "environment.yaml",
    )

    IGNORED_DIRECTORIES = {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "node_modules",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".next",
        "dist",
        "build",
    }

    def __init__(self, timeout=15, max_search_depth=4):
        self.name = "Environment Checker"
        self.timeout = timeout
        self.max_search_depth = max_search_depth

        self.environment_directories = self.ENVIRONMENT_DIRECTORIES

    # ---------------------------------------------------------
    # Public API
    # ---------------------------------------------------------

    def discover_environment(self, project_path):
        """
        Find a usable virtual environment belonging to the project.

        Searches common environment directories at the project root
        and inside project subdirectories.

        The project's parent directories and unrelated user environments
        are never searched.
        """
        project = Path(project_path).expanduser().resolve()

        if not project.exists() or not project.is_dir():
            return {
                "status": "error",
                "message": f"Invalid project directory: {project}",
                "project_path": str(project),
                "python": None,
                "python_version": None,
                "environment_path": None,
                "environment_type": None,
            }

        candidates = self._find_environment_directories(project)

        for environment_path in candidates:
            python_path = self._python_executable(environment_path)

            if not python_path:
                continue

            result = self._inspect_interpreter(python_path)

            if result["status"] != "success":
                continue

            resolved_environment = environment_path.resolve()

            # Verify the interpreter really belongs to this environment.
            interpreter_prefix = Path(result["prefix"]).resolve()

            try:
                interpreter_prefix.relative_to(resolved_environment)
            except ValueError:
                continue

            relative_path = resolved_environment.relative_to(project)

            return {
                **result,
                "status": "success",
                "message": "Project virtual environment found.",
                "project_path": str(project),
                "environment_path": str(resolved_environment),
                "environment_type": (
                    "project_virtualenv"
                    if relative_path == Path(".")
                    else "nested_project_virtualenv"
                ),
                "environment_relative_path": str(relative_path),
            }

        return {
            "status": "not_found",
            "message": (
                "No usable project-local Python virtual environment "
                "was found."
            ),
            "project_path": str(project),
            "python": None,
            "python_version": None,
            "environment_path": None,
            "environment_type": None,
        }

    def discover_manifests(self, project_path):
        """
        Find dependency manifest files inside the project.

        Does not scan outside the project directory.
        """
        project = Path(project_path).expanduser().resolve()

        if not project.exists() or not project.is_dir():
            return []

        manifests = []

        for directory in self._walk_project(project):
            for filename in self.MANIFEST_NAMES:
                candidate = directory / filename

                if candidate.is_file():
                    manifests.append({
                        "name": candidate.name,
                        "path": str(candidate),
                        "relative_path": str(
                            candidate.relative_to(project)
                        ),
                        "ecosystem": (
                            "Conda"
                            if candidate.name in {
                                "environment.yml",
                                "environment.yaml",
                            }
                            else "Python"
                        ),
                    })

        return sorted(
            manifests,
            key=lambda item: item["relative_path"].lower(),
        )

    def inspect_environment(self, project_path):
        """
        Inspect the discovered environment and list installed packages.

        If no environment is found, return an empty package inventory
        instead of inspecting the current Python interpreter.
        """
        environment = self.discover_environment(project_path)
        manifests = self.discover_manifests(project_path)

        if environment["status"] != "success":
            return {
                **environment,
                "installed_packages": {},
                "package_count": 0,
                "manifests": manifests,
                "manifest_count": len(manifests),
            }

        python_path = environment["python"]

        script = r"""
import importlib.metadata
import json
import platform
import sys

packages = {}

for distribution in importlib.metadata.distributions():
    name = distribution.metadata.get("Name")

    if not name:
        continue

    try:
        version = distribution.version
    except Exception:
        version = None

    normalized = name.lower().replace("_", "-").replace(".", "-")

    packages[normalized] = {
        "name": name,
        "version": version,
    }

print(json.dumps({
    "python": sys.executable,
    "python_version": platform.python_version(),
    "implementation": platform.python_implementation(),
    "prefix": sys.prefix,
    "base_prefix": sys.base_prefix,
    "installed_packages": packages,
}))
"""

        try:
            completed = subprocess.run(
                [python_path, "-I", "-c", script],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )

            if completed.returncode != 0:
                return {
                    **environment,
                    "status": "error",
                    "message": (
                        completed.stderr.strip()
                        or "Could not inspect the Python environment."
                    ),
                    "installed_packages": {},
                    "package_count": 0,
                    "manifests": manifests,
                    "manifest_count": len(manifests),
                }

            data = json.loads(completed.stdout)

            packages = data.get("installed_packages", {})

            return {
                **environment,
                "status": "success",
                "python": data["python"],
                "python_version": data["python_version"],
                "implementation": data["implementation"],
                "prefix": data["prefix"],
                "base_prefix": data["base_prefix"],
                "installed_packages": packages,
                "package_count": len(packages),
                "manifests": manifests,
                "manifest_count": len(manifests),
            }

        except subprocess.TimeoutExpired:
            message = "Python environment inspection timed out."

        except (OSError, ValueError, KeyError) as exc:
            message = str(exc)

        return {
            **environment,
            "status": "error",
            "message": message,
            "installed_packages": {},
            "package_count": 0,
            "manifests": manifests,
            "manifest_count": len(manifests),
        }

    def verify_dependencies(self, project_path, dependencies):
        """
        Verify Python dependencies without installing packages.

        When an environment is unavailable, preserve dependency records
        and report environment_not_found instead of falsely reporting
        packages as missing.
        """
        environment = self.inspect_environment(project_path)

        python_dependencies = []

        for dependency in dependencies:
            if not isinstance(dependency, dict):
                continue

            ecosystem = str(
                dependency.get("ecosystem", "")
            ).strip().lower()

            if ecosystem != "python":
                continue

            name = dependency.get("name")

            if not name:
                continue

            python_dependencies.append(dependency)

        # No environment: package installation status is unknown.
        if environment["status"] != "success":
            results = []

            for dependency in python_dependencies:
                results.append({
                    **dependency,
                    "required_version": dependency.get("version"),
                    "installed": None,
                    "installed_version": None,
                    "status": "environment_not_found",
                    "environment_path": None,
                    "python_version": None,
                })

            return {
                "status": environment["status"],
                "message": environment.get("message"),
                "environment": environment,
                "dependencies": results,
                "summary": {
                    "total": len(results),
                    "installed": 0,
                    "missing": 0,
                    "version_mismatch": 0,
                    "version_unknown": 0,
                    "environment_not_found": len(results),
                },
            }

        installed_packages = environment["installed_packages"]
        results = []

        for dependency in python_dependencies:
            name = dependency["name"]
            normalized_name = self._normalize_name(name)

            installed = installed_packages.get(normalized_name)
            required_version = dependency.get("version")

            result = {
                **dependency,
                "required_version": required_version,
                "installed": installed is not None,
                "installed_version": (
                    installed.get("version") if installed else None
                ),
                "environment_path": environment["environment_path"],
                "python_version": environment["python_version"],
            }

            if installed is None:
                result["status"] = "missing"

            elif not required_version:
                result["status"] = "installed"

            else:
                result["status"] = self._check_version_constraint(
                    installed.get("version"),
                    required_version,
                )

            results.append(result)

        return {
            "status": "success",
            "message": "Dependency verification completed.",
            "environment": environment,
            "dependencies": results,
            "summary": self._summarize(results),
        }

    # ---------------------------------------------------------
    # Project traversal
    # ---------------------------------------------------------

    def _walk_project(self, project):
        """
        Yield project directories without entering dependency caches,
        Git internals, or discovered virtual environments.
        """
        project = Path(project).resolve()

        for current, directories, _files in __import__("os").walk(project):
            current_path = Path(current)
            relative = current_path.relative_to(project)

            depth = len(relative.parts)

            if depth >= self.max_search_depth:
                directories[:] = []
                continue

            directories[:] = [
                name
                for name in directories
                if name not in self.IGNORED_DIRECTORIES
                and name not in self.ENVIRONMENT_DIRECTORIES
            ]

            yield current_path

    def _find_environment_directories(self, project):
        """
        Find conventional virtual environment directories.

        Search is bounded to prevent unnecessarily scanning huge projects.
        """
        candidates = []

        for directory in self._walk_project(project):
            for name in self.environment_directories:
                candidate = directory / name

                if candidate.is_dir():
                    candidates.append(candidate)

        # Prefer shallower environments.
        candidates.sort(
            key=lambda path: (
                len(path.relative_to(project).parts),
                str(path).lower(),
            )
        )

        return candidates

    # ---------------------------------------------------------
    # Python interpreter discovery
    # ---------------------------------------------------------

    def _python_executable(self, environment_path):
        """
        Return a candidate Python executable for a virtual environment.
        """
        if sys.platform == "win32":
            candidates = [
                environment_path / "Scripts" / "python.exe",
                environment_path / "Scripts" / "python",
            ]
        else:
            candidates = [
                environment_path / "bin" / "python",
                environment_path / "bin" / "python3",
            ]

        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)

        return None

    def _inspect_interpreter(self, python_path):
        """
        Confirm that the interpreter runs inside a virtual environment.
        """
        script = (
            "import json, platform, sys; "
            "print(json.dumps({"
            "'python': sys.executable, "
            "'python_version': platform.python_version(), "
            "'prefix': sys.prefix, "
            "'base_prefix': sys.base_prefix"
            "}))"
        )

        try:
            completed = subprocess.run(
                [python_path, "-I", "-c", script],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )

            if completed.returncode != 0:
                return {
                    "status": "error",
                    "message": (
                        completed.stderr.strip()
                        or "Could not run the candidate interpreter."
                    ),
                    "python": python_path,
                    "python_version": None,
                }

            data = json.loads(completed.stdout)

            if data["prefix"] == data["base_prefix"]:
                return {
                    "status": "error",
                    "message": (
                        "The candidate interpreter does not appear "
                        "to be running inside a virtual environment."
                    ),
                    "python": data["python"],
                    "python_version": data["python_version"],
                }

            return {
                "status": "success",
                "python": data["python"],
                "python_version": data["python_version"],
                "prefix": data["prefix"],
                "base_prefix": data["base_prefix"],
            }

        except subprocess.TimeoutExpired:
            message = "Python interpreter inspection timed out."

        except (OSError, ValueError, KeyError) as exc:
            message = str(exc)

        return {
            "status": "error",
            "message": message,
            "python": python_path,
            "python_version": None,
        }

    # ---------------------------------------------------------
    # Package verification helpers
    # ---------------------------------------------------------

    def _normalize_name(self, name):
        """
        Normalize package names using Python distribution conventions.
        """
        return re.sub(r"[-_.]+", "-", str(name).strip().lower())

    def _check_version_constraint(self, installed_version, requirement):
        """
        Compare an installed version against a version constraint.

        Returns:
        - installed
        - version_mismatch
        - version_unknown
        """
        if not installed_version:
            return "version_unknown"

        try:
            from packaging.specifiers import SpecifierSet
            from packaging.version import Version

            installed = Version(installed_version)
            constraint = str(requirement).strip()

            if not constraint:
                return "installed"

            if constraint.startswith(("===", "==", "!=", "<", ">", "~=")):
                pass
            elif constraint.startswith("="):
                constraint = constraint[1:]
            else:
                # A bare version such as 1.2.3 means exact match.
                constraint = f"=={constraint}"

            specifiers = SpecifierSet(constraint)

            if specifiers.contains(installed, prereleases=True):
                return "installed"

            return "version_mismatch"

        except Exception:
            # Do not guess if a requirement format is unsupported.
            return "version_unknown"

    def _summarize(self, dependencies):
        summary = {
            "total": len(dependencies),
            "installed": 0,
            "missing": 0,
            "version_mismatch": 0,
            "version_unknown": 0,
            "environment_not_found": 0,
        }

        for dependency in dependencies:
            status = dependency.get("status")

            if status in summary:
                summary[status] += 1

        return summary