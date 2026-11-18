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

    def get_container_details(self, container_id):

        result = self.execute_command([
            self.docker_path,
            "inspect",
            container_id
        ])

        if not result["success"]:
            return {
                "success": False,
                "details": None,
                "error": result["error"]
            }

        try:
            data = json.loads(result["output"])[0]

            state = data.get("State", {})
            config = data.get("Config", {})
            host_config = data.get("HostConfig", {})
            network_settings = data.get("NetworkSettings", {})

            ports = network_settings.get("Ports") or {}

            port_info = []

            for container_port, bindings in ports.items():
                if bindings:
                    for binding in bindings:
                        port_info.append(
                            f"{binding.get('HostIp', '0.0.0.0')}:"
                            f"{binding.get('HostPort')} -> {container_port}"
                        )
                else:
                    port_info.append(
                        f"{container_port} (not published)"
                    )

            mounts = []

            for mount in data.get("Mounts", []):
                mounts.append({
                    "type": mount.get("Type", ""),
                    "source": mount.get("Source", ""),
                    "destination": mount.get("Destination", ""),
                    "mode": mount.get("Mode", ""),
                    "rw": mount.get("RW", False)
                })

            networks = []

            for name, network in (
                network_settings.get("Networks") or {}
            ).items():
                networks.append({
                    "name": name,
                    "ip_address": network.get("IPAddress", ""),
                    "gateway": network.get("Gateway", "")
                })

            details = {
                "id": data.get("Id", ""),
                "name": data.get("Name", "").lstrip("/"),
                "image": config.get("Image", ""),
                "created": data.get("Created", ""),
                "status": state.get("Status", ""),
                "running": state.get("Running", False),
                "started_at": state.get("StartedAt", ""),
                "finished_at": state.get("FinishedAt", ""),
                "restart_policy": (
                    host_config.get("RestartPolicy", {}).get("Name", "no")
                ),
                "ports": port_info,
                "mounts": mounts,
                "networks": networks
            }

            return {
                "success": True,
                "details": details,
                "error": None
            }

        except (json.JSONDecodeError, IndexError, TypeError) as error:
            return {
                "success": False,
                "details": None,
                "error": str(error)
            }


    def get_container_logs(self, container_id, tail=200):

        if not self.is_docker_installed():
            return {
                "success": False,
                "logs": "",
                "error": "Docker is not installed."
            }

        try:
            result = subprocess.run(
                [
                    self.docker_path,
                    "logs",
                    "--timestamps",
                    "--tail",
                    str(tail),
                    container_id
                ],
                capture_output=True,
                text=True,
                timeout=30
            )

            logs = result.stdout + result.stderr

            return {
                "success": result.returncode == 0,
                "logs": logs.strip(),
                "error": (
                    result.stderr.strip()
                    if result.returncode != 0
                    else None
                )
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "logs": "",
                "error": "Fetching container logs timed out."
            }

        except Exception as error:
            return {
                "success": False,
                "logs": "",
                "error": str(error)
            }


    def get_container_stats(self):
        if not self.is_docker_installed():
            return {
                "success": False,
                "stats": [],
                "error": "Docker is not installed."
            }

        status = self.get_docker_status()

        if status["status"] != "running":
            return {
                "success": False,
                "stats": [],
                "error": "Docker daemon is not running or accessible."
            }

        result = self.execute_command(
            [
                self.docker_path,
                "stats",
                "--no-stream",
                "--format",
                "{{json .}}"
            ],
            timeout=15
        )

        if not result["success"]:
            return {
                "success": False,
                "stats": [],
                "error": result["error"]
            }

        stats = []

        for line in result["output"].splitlines():
            try:
                data = json.loads(line)

                stats.append({
                    "container": data.get("Container", ""),
                    "name": data.get("Name", ""),
                    "cpu": data.get("CPUPerc", "0%"),
                    "memory_usage": data.get("MemUsage", "0B / 0B"),
                    "memory_percent": data.get("MemPerc", "0%"),
                    "network_io": data.get("NetIO", "0B / 0B"),
                    "block_io": data.get("BlockIO", "0B / 0B"),
                    "pids": data.get("PIDs", "0")
                })

            except (json.JSONDecodeError, TypeError):
                continue

        return {
            "success": True,
            "stats": stats,
            "error": None
        }

    def get_container_stats_summary(self):
        result = self.get_container_stats()

        if not result["success"]:
            return result

        stats = result["stats"]

        return {
            "success": True,
            "total_monitored": len(stats),
            "stats": stats,
            "error": None
        }

    def get_images(self):
        if not self.is_docker_installed():
            return {
                "success": False,
                "images": [],
                "error": "Docker is not installed."
            }

        status = self.get_docker_status()

        if status["status"] != "running":
            return {
                "success": False,
                "images": [],
                "error": "Docker daemon is not running or accessible."
            }

        result = self.execute_command(
            [
                self.docker_path,
                "image",
                "ls",
                "--no-trunc",
                "--format",
                "{{json .}}"
            ],
            timeout=15
        )

        if not result["success"]:
            return {
                "success": False,
                "images": [],
                "error": result["error"]
            }

        images = []

        for line in result["output"].splitlines():
            try:
                data = json.loads(line)

                images.append({
                    "repository": data.get("Repository", ""),
                    "tag": data.get("Tag", ""),
                    "id": data.get("ID", ""),
                    "created": data.get("CreatedSince", ""),
                    "size": data.get("Size", "")
                })

            except (json.JSONDecodeError, TypeError):
                continue

        return {
            "success": True,
            "images": images,
            "total": len(images),
            "error": None
        }

    def get_image_details(self, image_id):
        if not self.is_docker_installed():
            return {
                "success": False,
                "details": None,
                "error": "Docker is not installed."
            }

        result = self.execute_command(
            [
                self.docker_path,
                "image",
                "inspect",
                image_id
            ],
            timeout=15
        )

        if not result["success"]:
            return {
                "success": False,
                "details": None,
                "error": result["error"]
            }

        try:
            data = json.loads(result["output"])[0]

            config = data.get("Config") or {}
            size = data.get("Size", 0)

            details = {
                "id": data.get("Id", ""),
                "repo_tags": data.get("RepoTags") or [],
                "created": data.get("Created", ""),
                "size": self.format_image_size(size),
                "architecture": data.get("Architecture", ""),
                "os": data.get("Os", ""),
                "author": data.get("Author", ""),
                "working_dir": config.get("WorkingDir", ""),
                "entrypoint": config.get("Entrypoint") or [],
                "command": config.get("Cmd") or [],
                "environment": config.get("Env") or [],
                "exposed_ports": list(
                    (config.get("ExposedPorts") or {}).keys()
                ),
                "volumes": list(
                    (config.get("Volumes") or {}).keys()
                )
            }

            return {
                "success": True,
                "details": details,
                "error": None
            }

        except (json.JSONDecodeError, IndexError, TypeError):
            return {
                "success": False,
                "details": None,
                "error": "Unable to parse image details."
            }

    def format_image_size(self, size):
        try:
            size = float(size)

            for unit in ["B", "KB", "MB", "GB", "TB"]:
                if size < 1024:
                    return f"{size:.2f} {unit}"

                size /= 1024

            return f"{size:.2f} PB"

        except (ValueError, TypeError):
            return "Unknown"


    def pull_image(self, image_name):
        if not self.is_docker_installed():
            return {
                "success": False,
                "message": "Docker is not installed."
            }

        if not image_name or not image_name.strip():
            return {
                "success": False,
                "message": "Image name cannot be empty."
            }

        result = self.execute_command(
            [
                self.docker_path,
                "pull",
                image_name.strip()
            ],
            timeout=600
        )

        return {
            "success": result["success"],
            "message": (
                result["output"]
                if result["success"]
                else result["error"]
            )
        }


    def remove_image(self, image_id):
        if not self.is_docker_installed():
            return {
                "success": False,
                "message": "Docker is not installed."
            }

        if not image_id:
            return {
                "success": False,
                "message": "Image ID is required."
            }

        result = self.execute_command(
            [
                self.docker_path,
                "image",
                "rm",
                image_id
            ],
            timeout=30
        )

        return {
            "success": result["success"],
            "message": (
                result["output"]
                if result["success"]
                else result["error"]
            )
        }