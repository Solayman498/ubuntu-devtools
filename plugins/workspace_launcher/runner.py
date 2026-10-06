from pathlib import Path
import subprocess


class ProjectRunner:

    def launch(self, project):

        project_path = Path(project["path"])
        project_type = project["type"]

        if not project_path.exists():
            return {
                "success": False,
                "status": "Project Not Found"
            }

        if project_type == "Python":
            return self._launch_python(project_path)

        return {
            "success": False,
            "status": f"{project_type} launcher not implemented yet"
        }

    def _launch_python(self, project_path):

        python = project_path / ".venv" / "bin" / "python"

        if not python.exists():
            python = project_path / "venv" / "bin" / "python"

        if not python.exists():
            return {
                "success": False,
                "status": "Python Environment Not Found"
            }

        entry_file = self._find_entry_file(project_path)

        if not entry_file:
            return {
                "success": False,
                "status": "Python Entry File Not Found"
            }

        try:
            process = subprocess.Popen(
                [str(python), str(entry_file)],
                cwd=str(project_path)
            )

            return {
                "success": True,
                "status": "Project Launched",
                "pid": process.pid,
                "entry_file": str(entry_file)
            }

        except OSError as error:
            return {
                "success": False,
                "status": "Launch Failed",
                "error": str(error)
            }

    def _find_entry_file(self, project_path):

        preferred = [
            "app.py",
            "main.py",
            "server.py",
            "run.py"
        ]

        for name in preferred:

            matches = list(project_path.rglob(name))

            if matches:
                return matches[0]

        return None