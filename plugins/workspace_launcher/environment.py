import os
from pathlib import Path
import subprocess
import shutil


class EnvironmentManager:

    def __init__(self):
        self.name = "Environment Manager"

    def analyze_environment(self, project):
        project_path = Path(project["path"])

        result = {
            "project": project["name"],
            "path": str(project_path),
            "type": project["type"],
            "runtime": None,
            "runtime_version": None,
            "environment_exists": False,
            "environment_path": None,
            "disk_free_gb": None,
            "disk_status": "Unknown",
            "status": "Unknown",
            "actions": []
        }

        if not project_path.exists():
            result["status"] = "Project Not Found"
            return result

        disk = self.check_disk_space("/")

        result["disk_free_gb"] = disk["free_gb"]

        if disk["free_gb"] is not None:

            if disk["free_gb"] < 1:
                result["disk_status"] = "Critical"

            elif disk["free_gb"] < 3:
                result["disk_status"] = "Low"

            else:
                result["disk_status"] = "Healthy"

        project_type = project["type"]
        if project_type == "Python":
            return self._analyze_python(
                project_path,
                result
            )

        if project_type in {
            "Node.js",
            "JavaScript",
            "TypeScript"
        }:
            return self._analyze_node(
                project_path,
                result
            )

        if project_type in {
            "C#",
            ".NET"
        }:
            return self._analyze_dotnet(
                project_path,
                result
            )

        result["status"] = "Runtime Detection Required"
        result["actions"].append(
            "Runtime analysis not implemented yet"
        )

        return result
    # -------------------------------------------------
    # Python
    # -------------------------------------------------

    def _get_pip_path(self, environment_path: Path) -> Path:
        """ Cross-platform virtual environment pip path identifier """
        if os.name == "nt":
            return environment_path / "Scripts" / "pip.exe"
        return environment_path / "bin" / "pip"

    def _analyze_python(self, project_path, result):
        result["runtime"] = "Python"

        python_path = shutil.which("python3") or shutil.which("python")

        if python_path:
            result["runtime_version"] = self._get_version([python_path, "--version"])

        environment_paths = [
            project_path / ".venv",
            project_path / "venv",
            project_path / "env"
        ]

        for environment in environment_paths:
            if environment.is_dir():
                result["environment_exists"] = True
                result["environment_path"] = str(environment)
                break

        if not python_path:
            result["status"] = "Runtime Missing"
            result["actions"].append("Install Python 3")
            return result

        if not result["environment_exists"]:
            result["status"] = "Environment Missing"
            result["actions"].append("Create Python virtual environment")
        else:
            result["status"] = "Ready"

        return result

    def create_python_environment(self, project_path):
        project_path = Path(project_path)
        environment_path = project_path / ".venv"

        if environment_path.exists():
            return {
                "success": True,
                "status": "Already Exists",
                "path": str(environment_path)
            }

        python_path = shutil.which("python3") or shutil.which("python")

        if not python_path:
            return {
                "success": False,
                "status": "Python Not Found",
                "path": None
            }

        try:
            result = subprocess.run(
                [python_path, "-m", "venv", str(environment_path)],
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode != 0:
                return {
                    "success": False,
                    "status": "Creation Failed",
                    "path": str(environment_path),
                    "error": result.stderr.strip()
                }

            return {
                "success": True,
                "status": "Created",
                "path": str(environment_path)
            }

        except (subprocess.SubprocessError, OSError) as error:
            return {
                "success": False,
                "status": "Creation Failed",
                "path": str(environment_path),
                "error": str(error)
            }

    def install_python_dependencies(
        self,
        project_path,
        dependencies
    ):

        command_result = self.build_python_install_command(
            project_path,
            dependencies
        )

        if not command_result["success"]:
            return command_result

        command = command_result["command"]

        if not command:
            return {
                "success": True,
                "status": "No Dependencies"
            }

        try:

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=1200
            )

            if result.returncode != 0:

                return {
                    "success": False,
                    "status": "Installation Failed",
                    "error": result.stderr.strip(),
                    "output": result.stdout.strip()
                }

            return {
                "success": True,
                "status": "Dependencies Installed",
                "installed": command[3:],
                "output": result.stdout.strip()
            }

        except subprocess.TimeoutExpired:

            return {
                "success": False,
                "status": "Installation Timed Out"
            }

        except OSError as error:

            return {
                "success": False,
                "status": "Installation Failed",
                "error": str(error)
            }

    # -------------------------------------------------
    # Node.js
    # -------------------------------------------------

    def _analyze_node(self, project_path, result):
        result["runtime"] = "Node.js"

        node_path = shutil.which("node")

        if node_path:
            result["runtime_version"] = self._get_version([node_path, "--version"])

        node_modules = project_path / "node_modules"
        package_json = project_path / "package.json"

        if node_modules.is_dir():
            result["environment_exists"] = True
            result["environment_path"] = str(node_modules)

        if not node_path:
            result["status"] = "Runtime Missing"
            result["actions"].append("Install Node.js")
            return result

        if not package_json.exists():
            result["status"] = "package.json Missing"
            result["actions"].append("Project manifest not found")
            return result

        if not result["environment_exists"]:
            result["status"] = "Dependencies Missing"
            result["actions"].append("Install Node.js dependencies")
        else:
            result["status"] = "Ready"

        return result

    # -------------------------------------------------
    # .NET / C#
    # -------------------------------------------------

    def _analyze_dotnet(self, project_path, result):
        result["runtime"] = ".NET"

        dotnet_path = shutil.which("dotnet")

        if dotnet_path:
            result["runtime_version"] = self._get_version([dotnet_path, "--version"])

        csproj_files = list(project_path.rglob("*.csproj"))

        if not dotnet_path:
            result["status"] = "Runtime Missing"
            result["actions"].append("Install .NET SDK")
            return result

        if not csproj_files:
            result["status"] = "Project File Missing"
            result["actions"].append("No .csproj file found")
            return result

        result["status"] = "Ready"
        result["environment_exists"] = True
        result["environment_path"] = str(csproj_files[0])

        return result

    # -------------------------------------------------
    # Utility & Plan Building
    # -------------------------------------------------

    def _get_version(self, command):
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=5
            )

            output = result.stdout.strip() or result.stderr.strip()
            return output

        except (subprocess.SubprocessError, OSError):
            return None

    def build_installation_plan(self, dependencies, ecosystem):
        packages = []

        for dependency in dependencies:
            if dependency.get("ecosystem") != ecosystem:
                continue

            classification = dependency.get("classification")
            if classification not in {"declared_external", "undeclared_external"}:
                continue

            name = dependency.get("name")
            if not name:
                continue

            version = dependency.get("version")
            if version:
                package = f"{name}{version}"
            else:
                package = name

            packages.append(package)

        return {
            "ecosystem": ecosystem,
            "packages": packages,
            "count": len(packages)
        }
    
    def check_disk_space(self, path="/"):
        try:
            usage = shutil.disk_usage(path)

            return {
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "free_gb": round(
                    usage.free / (1024 ** 3),
                    2
                )
            }

        except OSError as error:
            return {
                "total": None,
                "used": None,
                "free": None,
                "free_gb": None,
                "error": str(error)
            }

    def build_python_install_command(self, project_path, dependencies):
        project_path = Path(project_path)
        environment_path = project_path / ".venv"
        pip_path = self._get_pip_path(environment_path)

        if not pip_path.exists():
            return {
                "success": False,
                "command": None,
                "status": "pip Not Found"
            }

        plan = self.build_installation_plan(dependencies, ecosystem="Python")
        packages = plan["packages"]

        if not packages:
            return {
                "success": True,
                "command": None,
                "status": "No Dependencies"
            }

        command = [str(pip_path), "install", *packages]

        return {
            "success": True,
            "command": command,
            "status": "Ready"
        }