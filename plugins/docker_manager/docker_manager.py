import subprocess
import shutil
import json


class DockerManager:

    def get_dashboard_summary(self):

        docker_status = self.get_docker_status()

        if docker_status["status"] != "running":
            return {
                "available": False,
                "status": docker_status,
                "containers": {
                    "total": 0,
                    "running": 0,
                    "stopped": 0
                },
                "images": 0,
                "volumes": 0
            }

        containers_result = self.get_containers()

        if not containers_result["success"]:
            return {
                "available": False,
                "status": docker_status,
                "error": containers_result["error"]
            }

        containers = containers_result["containers"]

        running = sum(
            1 for c in containers
            if c["state"].lower() == "running"
        )

        stopped = len(containers) - running

        images_result = self.execute_command([
            self.docker_path,
            "images",
            "-q"
        ])

        volumes_result = self.execute_command([
            self.docker_path,
            "volume",
            "ls",
            "-q"
        ])

        return {
            "available": True,
            "status": docker_status,
            "containers": {
                "total": len(containers),
                "running": running,
                "stopped": stopped
            },
            "images": len(set(
                images_result["output"].splitlines()
            )) if images_result["success"] else 0,
            "volumes": len(set(
                volumes_result["output"].splitlines()
            )) if volumes_result["success"] else 0
        }

    def __init__(self):
        self.name = "Docker Manager"
        self.docker_path = shutil.which("docker")

    # =========================================
    # BASIC INFORMATION
    # =========================================

    def get_name(self):
        return self.name

    def is_docker_installed(self):
        self.docker_path = shutil.which("docker")
        return self.docker_path is not None

    # =========================================
    # COMMAND EXECUTION
    # =========================================

    def execute_command(self, command, timeout=30):

        if not self.is_docker_installed():
            return {
                "success": False,
                "output": "",
                "error": "Docker is not installed."
            }

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            return {
                "success": result.returncode == 0,
                "output": result.stdout.strip(),
                "error": result.stderr.strip() or None
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "output": "",
                "error": "Docker command timed out."
            }

        except Exception as error:
            return {
                "success": False,
                "output": "",
                "error": str(error)
            }

    # =========================================
    # DOCKER VERSION
    # =========================================

    def get_docker_version(self):

        if not self.is_docker_installed():
            return None

        return self.execute_command([
            self.docker_path,
            "--version"
        ])

    # =========================================
    # DOCKER STATUS DETECTION
    # =========================================

    def get_docker_status(self):

        # Check installation
        if not self.is_docker_installed():

            return {
                "status": "not_installed",
                "installed": False,
                "running": False,
                "version": None,
                "message": "Docker is not installed."
            }

        # Get Docker version
        version_result = self.get_docker_version()

        version = (
            version_result["output"]
            if version_result and version_result["success"]
            else None
        )

        # Check Docker daemon
        daemon_result = self.execute_command([
            self.docker_path,
            "info",
            "--format",
            "{{.ServerVersion}}"
        ])

        if daemon_result["success"]:

            return {
                "status": "running",
                "installed": True,
                "running": True,
                "version": version,
                "server_version": daemon_result["output"],
                "message": "Docker is running."
            }

        # Docker installed but daemon unavailable
        return {
            "status": "installed_stopped",
            "installed": True,
            "running": False,
            "version": version,
            "message": "Docker is installed but not accessible."
        }

    # =========================================
    # CONTAINER MANAGEMENT
    # =========================================

    def get_containers(self, all_containers=True):

        command = [
            self.docker_path,
            "ps"
        ]

        if all_containers:
            command.append("-a")

        command.extend([
            "--format",
            "{{json .}}"
        ])

        result = self.execute_command(command)

        if not result["success"]:
            return {
                "success": False,
                "containers": [],
                "error": result["error"]
            }

        containers = []

        for line in result["output"].splitlines():

            try:
                container = json.loads(line)

                containers.append({
                    "id": container.get("ID", ""),
                    "name": container.get("Names", ""),
                    "image": container.get("Image", ""),
                    "command": container.get("Command", ""),
                    "status": container.get("Status", ""),
                    "state": container.get("State", ""),
                    "ports": container.get("Ports", "")
                })

            except json.JSONDecodeError:
                continue

        return {
            "success": True,
            "containers": containers,
            "error": None
        }

    # =========================================
    # CONTAINER ACTIONS
    # =========================================

    def start_container(self, container_id):

        return self.execute_command([
            self.docker_path,
            "start",
            container_id
        ])

    def stop_container(self, container_id):

        return self.execute_command([
            self.docker_path,
            "stop",
            container_id
        ])

    def restart_container(self, container_id):

        return self.execute_command([
            self.docker_path,
            "restart",
            container_id
        ])

    def remove_container(self, container_id, force=False):

        command = [
            self.docker_path,
            "rm"
        ]

        if force:
            command.append("-f")

        command.append(container_id)

        return self.execute_command(command)
    
    def get_installation_command(self):

        return [
            "apt-get",
            "update"
        ]

    def install_docker(self):

        if self.is_docker_installed():
            return {
                "success": False,
                "message": "Docker is already installed."
            }

        return {
            "success": False,
            "message": (
                "Docker installation requires administrator "
                "authentication. Installation workflow is not "
                "configured yet."
            )
        }

    def start_docker_service(self):

        if not self.is_docker_installed():
            return {
                "success": False,
                "message": "Docker is not installed."
            }

        result = subprocess.run(
            [
                "pkexec",
                "systemctl",
                "start",
                "docker"
            ],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:

            return {
                "success": True,
                "message": "Docker service started successfully."
            }

        return {
            "success": False,
            "message": result.stderr.strip() or "Unable to start Docker."
        }


    def stop_docker_service(self):

        if not self.is_docker_installed():
            return {
                "success": False,
                "message": "Docker is not installed."
            }

        result = subprocess.run(
            [
                "pkexec",
                "systemctl",
                "stop",
                "docker"
            ],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:

            return {
                "success": True,
                "message": "Docker service stopped successfully."
            }

        return {
            "success": False,
            "message": result.stderr.strip() or "Unable to stop Docker."
        }