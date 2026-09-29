from pathlib import Path


class DependencyClassifier:

    def __init__(self):
        self.name = "Dependency Classifier"
        self.skip_directories = {
            ".git",
            ".vscode",
            ".idea",
            ".cache",
            "__pycache__",
            "node_modules",
            "venv",
            ".venv",
            "env",
            ".env",
            "dist",
            "build",
            "target",
            "bin",
            "obj",
        }

    def classify(
        self,
        project_path,
        dependency_name,
        ecosystem,
        declared_dependencies=None
    ):

        declared_dependencies = declared_dependencies or set()

        if dependency_name in declared_dependencies:
            return "declared_external"

        if self.is_builtin(
            dependency_name,
            ecosystem
        ):
            return "built_in"

        if self.is_local_dependency(
            project_path,
            dependency_name,
            ecosystem
        ):
            return "local"

        return "undeclared_external"

    def is_local_dependency(
        self,
        project_path,
        dependency_name,
        ecosystem
    ):

        project = Path(project_path)

        if ecosystem == "Python":
            return self._is_local_python(
                project,
                dependency_name
            )

        if ecosystem in {"JavaScript", "TypeScript"}:
            return dependency_name.startswith(".")

        if ecosystem in {"C", "C++"}:
            return (project / dependency_name).exists()

        if ecosystem == "C#":
            return self._is_local_namespace(
                project,
                dependency_name
            )

        if ecosystem == "Java":
            return self._is_local_namespace(
                project,
                dependency_name
            )

        if ecosystem == "Go":
            return (
                dependency_name.startswith("./")
                or "/internal/" in dependency_name
            )

        if ecosystem == "Rust":
            return self._is_local_rust(
                project,
                dependency_name
            )

        if ecosystem in {"PHP", "Ruby", "Dart"}:
            return (project / dependency_name).exists()

        return False

    def is_builtin(
        self,
        dependency_name,
        ecosystem
    ):

        if ecosystem == "Python":
            import sys
            return dependency_name in sys.stdlib_module_names

        if ecosystem == "Java":
            return dependency_name in {
                "java",
                "javax",
                "jdk",
                "sun"
            }

        if ecosystem in {"C", "C++"}:
            return dependency_name in {
                "stdio.h",
                "stdlib.h",
                "string.h",
                "math.h",
                "iostream",
                "vector",
                "string",
                "map",
                "set",
                "algorithm"
            }

        if ecosystem == "Dart":
            return dependency_name.startswith("dart:")

        return False

    def _is_local_python(
        self,
        project,
        dependency
    ):

        module_names = set()

        def scan(directory):

            try:
                children = directory.iterdir()
            except (PermissionError, OSError):
                return

            for path in children:

                if path.is_symlink():
                    continue

                if path.is_dir():

                    if path.name in self.skip_directories:
                        continue

                    scan(path)

                elif path.is_file() and path.suffix == ".py":

                    relative = path.relative_to(project)

                    if path.name == "__init__.py":

                        package_parts = relative.parent.parts

                        for part in package_parts:
                            module_names.add(part)

                    else:
                        module_names.add(path.stem)

        scan(project)

        return dependency in module_names

        

    def _is_local_namespace(
        self,
        project,
        dependency
    ):

        project_name = project.name

        return (
            dependency == project_name
            or dependency.startswith(
                project_name + "."
            )
        )

    def _is_local_rust(
        self,
        project,
        dependency
    ):

        src = project / "src"

        if not src.exists():
            return False

        return (
            (src / f"{dependency}.rs").exists()
            or (src / dependency).is_dir()
        )