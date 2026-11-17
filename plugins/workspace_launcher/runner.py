from pathlib import Path
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
import xml.etree.ElementTree as ET


class ProjectRunner:

    def __init__(self):
        self.processes = {}

    # --------------------------------------------------
    # Main Launch
    # --------------------------------------------------

    def launch(self, project):

        project_path = Path(project["path"]).expanduser().resolve()

        if not project_path.is_dir():
            return {
                "success": False,
                "status": "Project Not Found"
            }

        self.processes = {}

        try:
            # 1. Detect frontend
            frontend = self._find_frontend(project_path)

            # 2. Detect backend
            backend = self._find_backend(project_path)

            # 3. Launch backend first
            backend_result = None

            if backend:
                backend_result = self._launch_backend(backend)

                if not backend_result["success"]:
                    return backend_result

            # 4. Launch frontend
            frontend_result = None

            if frontend:
                frontend_result = self._launch_frontend(frontend)

                if not frontend_result["success"]:
                    return frontend_result

            # 5. Open browser after frontend is ready
            frontend_url = None

            if frontend_result:
                frontend_url = frontend_result.get("url")

                if frontend_url:
                    webbrowser.open(frontend_url)
            elif backend_result and backend_result.get("url"):
                webbrowser.open(backend_result.get("url"))

            if not backend and not frontend:
                return {
                    "success": False,
                    "status": "No Supported Launch Configuration Found",
                    "error": (
                        "Could not detect a supported backend "
                        "or frontend configuration."
                    )
                }

            all_pids = {
                name: process.pid
                for name, process in self.processes.items()
            }

            return {
                "success": True,
                "status": "Project Launched",
                "pid": next(iter(all_pids.values()), None),
                "pids": all_pids,
                "backend": backend_result,
                "frontend": frontend_result,
                "url": frontend_url or (
                    backend_result.get("url")
                    if backend_result else None
                )
            }

        except Exception as error:
            return {
                "success": False,
                "status": "Launch Failed",
                "error": str(error)
            }

    # --------------------------------------------------
    # Frontend Detection
    # --------------------------------------------------

    def _find_frontend(self, project_path):

        possible_directories = [
            project_path / "frontend",
            project_path / "client",
            project_path / "web",
            project_path / "ui",
            project_path,
        ]

        for directory in possible_directories:

            if not directory.is_dir():
                continue

            package_file = directory / "package.json"

            if package_file.is_file():
                try:
                    with package_file.open(
                        "r",
                        encoding="utf-8"
                    ) as file:
                        package_data = json.load(file)

                    if package_data.get("scripts"):
                        return {
                            "type": "framework",
                            "path": directory,
                            "package": package_data
                        }

                except (OSError, json.JSONDecodeError):
                    pass

            index_file = directory / "index.html"

            if index_file.is_file():
                return {
                    "type": "static",
                    "path": directory,
                    "index": index_file
                }

        return None

    # --------------------------------------------------
    # Backend Detection
    # --------------------------------------------------

    def _find_backend(self, project_path):

        dotnet_backend = self._find_dotnet_backend(project_path)

        if dotnet_backend:
            return dotnet_backend

        possible_directories = [
            project_path / "backend",
            project_path / "server",
            project_path / "api",
            project_path,
        ]

        for directory in possible_directories:

            if not directory.is_dir():
                continue

            entry_file = self._find_python_entry(directory)

            if entry_file:
                return {
                    "type": "python",
                    "path": directory,
                    "entry": entry_file
                }

        return None

    # --------------------------------------------------
    # .NET Project Detection
    # --------------------------------------------------

    def _find_dotnet_backend(self, project_path):

        ignored = {
            ".git",
            ".venv",
            "venv",
            "env",
            "node_modules",
            "bin",
            "obj",
            "dist",
            "build",
        }

        project_files = []

        for current, dirs, files in os.walk(project_path):
            dirs[:] = [
                directory
                for directory in dirs
                if directory not in ignored
            ]

            for filename in files:
                if filename.lower().endswith(
                    (".csproj", ".fsproj", ".vbproj")
                ):
                    project_files.append(Path(current) / filename)

        if not project_files:
            return None

        candidates = []

        for project_file in project_files:
            score = 0

            try:
                tree = ET.parse(project_file)
                root = tree.getroot()
                sdk = root.attrib.get("Sdk", "").lower()

                if "microsoft.net.sdk.web" in sdk:
                    score += 100

                if "api" in project_file.stem.lower():
                    score += 40

                program_file = project_file.parent / "Program.cs"

                if program_file.is_file():
                    score += 20

                    try:
                        program_content = program_file.read_text(
                            encoding="utf-8",
                            errors="ignore"
                        )

                        if "WebApplication.CreateBuilder" in program_content:
                            score += 50
                    except OSError:
                        pass

                if (
                    project_file.parent / "appsettings.json"
                ).is_file():
                    score += 15

                if score > 0:
                    candidates.append(
                        (score, project_file)
                    )

            except (ET.ParseError, OSError):
                continue

        if not candidates:
            return None

        candidates.sort(
            key=lambda item: item[0],
            reverse=True
        )

        startup_project = candidates[0][1]

        return {
            "type": "dotnet",
            "path": project_path,
            "project": startup_project
        }

    # --------------------------------------------------
    # Python Entry Detection
    # --------------------------------------------------

    def _find_python_entry(self, directory):

        preferred = [
            "main.py",
            "app.py",
            "server.py",
            "run.py",
            "manage.py",
        ]

        ignored = {
            ".venv",
            "venv",
            "env",
            "__pycache__",
            "node_modules",
            ".git",
            "build",
            "dist",
        }

        for name in preferred:

            for match in directory.rglob(name):

                if any(
                    part in ignored
                    for part in match.relative_to(directory).parts
                ):
                    continue

                return match

        return None

    # --------------------------------------------------
    # Firebase Credentials Detection
    # --------------------------------------------------

    def _find_firebase_credentials(self, project_path):

        ignored = {
            ".git",
            "bin",
            "obj",
            "node_modules",
            ".venv",
            "venv",
        }

        matches = []

        for current, dirs, files in os.walk(project_path):
            dirs[:] = [
                directory
                for directory in dirs
                if directory not in ignored
            ]

            for filename in files:
                lower_name = filename.lower()

                if not lower_name.endswith(".json"):
                    continue

                if (
                    "firebase" in lower_name
                    and "adminsdk" in lower_name
                ) or "serviceaccount" in lower_name:
                    matches.append(
                        Path(current) / filename
                    )

        if not matches:
            return None

        # Prefer Infrastructure/Data credentials
        matches.sort(
            key=lambda item: (
                "infrastructure" not in str(item).lower(),
                "data" not in str(item.parent).lower(),
            )
        )

        return matches[0]

    # --------------------------------------------------
    # Backend Launcher
    # --------------------------------------------------

    def _launch_backend(self, backend):

        backend_type = backend["type"]

        if backend_type == "python":
            return self._launch_python_backend(backend)

        if backend_type == "dotnet":
            return self._launch_dotnet_backend(backend)

        return {
            "success": False,
            "status": f"Unsupported Backend: {backend_type}"
        }

    # --------------------------------------------------
    # .NET Backend Launcher
    # --------------------------------------------------

    def _launch_dotnet_backend(self, backend):

        dotnet = shutil.which("dotnet")

        if not dotnet:
            return {
                "success": False,
                "status": ".NET SDK Not Installed",
                "error": (
                    "Could not find the dotnet CLI. "
                    "Ensure the .NET SDK is installed and in PATH."
                )
            }

        try:
            sdk_version = subprocess.check_output(
                [dotnet, "--version"],
                text=True
            ).strip()
        except Exception:
            sdk_version = "unknown"

        project_path = backend["path"]
        project_file = backend["project"]
        project_directory = project_file.parent

        # --------------------------------------------------
        # Firebase Credentials Detection
        # --------------------------------------------------

        env_credentials = os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS"
        )

        if env_credentials:
            credentials = Path(
                env_credentials
            ).expanduser()

            if not credentials.is_file():
                return {
                    "success": False,
                    "status": "Firebase Credentials Not Found",
                    "error": (
                        "GOOGLE_APPLICATION_CREDENTIALS points "
                        "to a file that does not exist."
                    )
                }
        else:
            credentials = self._find_firebase_credentials(
                project_path
            )

        if not credentials:
            return {
                "success": False,
                "status": "Firebase Credentials Not Found",
                "error": (
                    "Could not locate Firebase Admin SDK JSON credentials."
                )
            }

        credentials = credentials.resolve()

        # --------------------------------------------------
        # Fixed API Port
        # --------------------------------------------------

        port = 5000
        host = "127.0.0.1"
        url = f"http://localhost:{port}"

        # Check whether port is already occupied
        try:
            with socket.socket(
                socket.AF_INET,
                socket.SOCK_STREAM
            ) as test_socket:

                test_socket.setsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_REUSEADDR,
                    1
                )

                test_socket.bind((host, port))

        except OSError:
            return {
                "success": False,
                "status": "Port Already In Use",
                "error": (
                    f"Port {port} is already occupied. "
                    "Stop the application using this port "
                    "and try again."
                )
            }

        # --------------------------------------------------
        # Environment Configuration
        # --------------------------------------------------

        environment = os.environ.copy()

        environment["ASPNETCORE_ENVIRONMENT"] = "Development"

        environment["ASPNETCORE_URLS"] = url

        environment["GOOGLE_APPLICATION_CREDENTIALS"] = str(
            credentials
        )

        # --------------------------------------------------
        # Launch ASP.NET Core API
        # --------------------------------------------------

        command = [
            dotnet,
            "run",
            "--project",
            str(project_file),
            "--urls",
            url
        ]

        try:
            process = subprocess.Popen(
                command,
                cwd=str(project_directory),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

            self.processes["backend"] = process

            # Wait until API becomes available
            if not self._wait_for_port(
                port,
                process,
                timeout=90
            ):

                try:
                    os.killpg(process.pid, 15)
                except OSError:
                    pass

                self.processes.pop("backend", None)

                return {
                    "success": False,
                    "status": "ASP.NET Core API Failed to Start",
                    "error": (
                        f"API did not become available at {url}. "
                        "Check the .NET project and its dependencies."
                    )
                }

            return {
                "success": True,
                "status": "ASP.NET Core API Started",
                "pid": process.pid,
                "project": str(project_file),
                "sdk": sdk_version,
                "url": url,
                "port": port,
                "environment": "Development",
                "firebase_credentials": str(credentials)
            }

        except OSError as error:

            self.processes.pop("backend", None)

            return {
                "success": False,
                "status": "ASP.NET Core Launch Failed",
                "error": str(error)
            }

    # --------------------------------------------------
    # Python Backend
    # --------------------------------------------------

    def _launch_python_backend(self, backend):

        backend_path = backend["path"]
        entry_file = backend["entry"]

        python_candidates = [
            backend_path / ".venv" / "bin" / "python",
            backend_path / "venv" / "bin" / "python",
            backend_path / "env" / "bin" / "python",
            backend_path.parent / ".venv" / "bin" / "python",
            backend_path.parent / "venv" / "bin" / "python",
        ]

        python = next(
            (
                candidate
                for candidate in python_candidates
                if candidate.is_file()
            ),
            None
        )

        if python is None:
            return {
                "success": False,
                "status": "Python Environment Not Found",
                "error": (
                    "Prepare the project's Python environment "
                    "before launching."
                )
            }

        try:
            process = subprocess.Popen(
                [str(python), str(entry_file)],
                cwd=str(backend_path),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

            self.processes["backend"] = process

            return {
                "success": True,
                "status": "Python Backend Started",
                "pid": process.pid,
                "entry_file": str(entry_file)
            }

        except OSError as error:
            return {
                "success": False,
                "status": "Python Backend Launch Failed",
                "error": str(error)
            }

    # --------------------------------------------------
    # Frontend Launcher
    # --------------------------------------------------

    def _launch_frontend(self, frontend):

        frontend_type = frontend["type"]

        if frontend_type == "static":
            return self._launch_static_frontend(frontend)

        if frontend_type == "framework":
            return self._launch_framework_frontend(frontend)

        return {
            "success": False,
            "status": "Unknown Frontend Type"
        }

    # --------------------------------------------------
    # Static HTML / CSS / JavaScript
    # --------------------------------------------------

    def _launch_static_frontend(self, frontend):

        directory = frontend["path"]

        python = (
            shutil.which("python3")
            or shutil.which("python")
        )

        if not python:
            return {
                "success": False,
                "status": "Python HTTP Server Unavailable"
            }

        port = self._find_free_port()

        try:
            process = subprocess.Popen(
                [
                    python,
                    "-m",
                    "http.server",
                    str(port),
                    "--bind",
                    "127.0.0.1",
                    "--directory",
                    str(directory)
                ],
                cwd=str(directory),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

            self.processes["frontend"] = process

            url = f"http://127.0.0.1:{port}/"

            if not self._wait_for_port(port, process):
                return {
                    "success": False,
                    "status": "Static Frontend Failed to Start"
                }

            return {
                "success": True,
                "status": "Static Frontend Started",
                "pid": process.pid,
                "url": url
            }

        except OSError as error:
            return {
                "success": False,
                "status": "Static Frontend Launch Failed",
                "error": str(error)
            }

    # --------------------------------------------------
    # React / Vue / Angular / Next / Other Node Frontends
    # --------------------------------------------------

    def _launch_framework_frontend(self, frontend):

        directory = frontend["path"]
        package = frontend["package"]

        scripts = package.get("scripts", {})

        if not scripts:
            return {
                "success": False,
                "status": "Frontend Scripts Not Found"
            }

        script_name = next(
            (
                name
                for name in ("dev", "start", "serve")
                if name in scripts
            ),
            None
        )

        if not script_name:
            return {
                "success": False,
                "status": "No Development Script Found",
                "error": (
                    "package.json must contain a dev, start "
                    "or serve script."
                )
            }

        package_manager = self._detect_package_manager(directory)

        executable = shutil.which(package_manager)

        if not executable:
            return {
                "success": False,
                "status": f"{package_manager} Not Installed"
            }

        if package_manager == "yarn":
            command = [executable, script_name]
        elif package_manager == "pnpm":
            command = [executable, "run", script_name]
        else:
            command = [executable, "run", script_name]

        port = self._get_framework_port(
            package,
            script_name
        )

        try:
            process = subprocess.Popen(
                command,
                cwd=str(directory),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

            self.processes["frontend"] = process

            if not self._wait_for_port(port, process):
                return {
                    "success": False,
                    "status": "Frontend Server Failed to Start",
                    "error": (
                        f"Could not detect a running frontend server "
                        f"on port {port}. Check the project's "
                        f"{script_name} script and configuration."
                    )
                }

            url = f"http://localhost:{port}/"

            return {
                "success": True,
                "status": "Framework Frontend Started",
                "pid": process.pid,
                "package_manager": package_manager,
                "script": script_name,
                "url": url
            }

        except OSError as error:
            return {
                "success": False,
                "status": "Framework Frontend Launch Failed",
                "error": str(error)
            }

    # --------------------------------------------------
    # Package Manager Detection
    # --------------------------------------------------

    def _detect_package_manager(self, directory):

        if (directory / "pnpm-lock.yaml").exists():
            return "pnpm"

        if (directory / "yarn.lock").exists():
            return "yarn"

        if (directory / "package-lock.json").exists():
            return "npm"

        package_manager = shutil.which("npm")

        if package_manager:
            return "npm"

        if shutil.which("pnpm"):
            return "pnpm"

        if shutil.which("yarn"):
            return "yarn"

        return "npm"

    # --------------------------------------------------
    # Framework Port Detection
    # --------------------------------------------------

    def _get_framework_port(self, package, script_name):

        scripts = package.get("scripts", {})
        script = scripts.get(script_name, "").lower()

        # Common framework defaults
        if "next" in script or "next" in package.get("dependencies", {}):
            return 3000

        if "angular" in package.get("dependencies", {}):
            return 4200

        if "vite" in package.get("devDependencies", {}):
            return 5173

        if "vue" in package.get("dependencies", {}):
            return 5173

        return 3000

    # --------------------------------------------------
    # Port Utilities
    # --------------------------------------------------

    def _find_free_port(self):

        with socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM
        ) as sock:

            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def _wait_for_port(self, port, process, timeout=30):

        start_time = time.time()

        while time.time() - start_time < timeout:

            if process.poll() is not None:
                return False

            try:
                with socket.create_connection(
                    ("127.0.0.1", port),
                    timeout=1
                ):
                    return True

            except OSError:
                time.sleep(0.5)

        return False

    # --------------------------------------------------
    # Stop Project
    # --------------------------------------------------

    def stop(self):

        stopped = []

        for name, process in list(self.processes.items()):

            if process.poll() is None:

                try:
                    os.killpg(
                        process.pid,
                        15
                    )

                    stopped.append(name)

                except OSError:
                    pass

        self.processes.clear()

        return {
            "success": True,
            "status": "Project Stopped",
            "stopped": stopped
        }