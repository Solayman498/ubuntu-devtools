from pathlib import Path
import sys


class DependencyClassifier:

    def __init__(self):

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

        # Common language keywords / tokens that can never be packages
        self.language_keywords = {

            "Python": {
                "and", "as", "assert", "async", "await",
                "break", "case", "class", "continue",
                "def", "del", "elif", "else", "except",
                "False", "finally", "for", "from", "global",
                "if", "import", "in", "is", "lambda",
                "match", "None", "nonlocal", "not", "or",
                "pass", "raise", "return", "True", "try",
                "while", "with", "yield"
            },

            "C#": {
                "abstract", "as", "base", "bool", "break",
                "byte", "case", "catch", "char", "checked",
                "class", "const", "continue", "decimal",
                "default", "delegate", "do", "double", "else",
                "enum", "event", "explicit", "extern", "false",
                "finally", "fixed", "float", "for", "foreach",
                "goto", "if", "implicit", "in", "int",
                "interface", "internal", "is", "lock", "long",
                "namespace", "new", "null", "object", "operator",
                "out", "override", "params", "private",
                "protected", "public", "readonly", "ref",
                "return", "sbyte", "sealed", "short", "sizeof",
                "stackalloc", "static", "string", "struct",
                "switch", "this", "throw", "true", "try",
                "typeof", "uint", "ulong", "unchecked",
                "unsafe", "ushort", "using", "virtual",
                "void", "volatile", "while", "var",
                "dynamic", "record", "init", "required"
            },

            "JavaScript": {
                "break", "case", "catch", "class", "const",
                "continue", "debugger", "default", "delete",
                "do", "else", "export", "extends", "false",
                "finally", "for", "function", "if", "import",
                "in", "instanceof", "let", "new", "null",
                "return", "super", "switch", "this", "throw",
                "true", "try", "typeof", "var", "void",
                "while", "with", "yield"
            },

            "TypeScript": {
                "break", "case", "catch", "class", "const",
                "continue", "debugger", "default", "delete",
                "do", "else", "export", "extends", "false",
                "finally", "for", "function", "if", "import",
                "in", "instanceof", "let", "new", "null",
                "return", "super", "switch", "this", "throw",
                "true", "try", "typeof", "var", "void",
                "while", "with", "yield", "interface",
                "type", "public", "private", "protected"
            }
        }

        self.builtin_names = {

            "Python": set(sys.stdlib_module_names),

            "Java": {
                "java",
                "javax",
                "jdk",
                "sun"
            },

            "C": {
                "stdio.h",
                "stdlib.h",
                "string.h",
                "math.h",
                "stdbool.h",
                "stdint.h"
            },

            "C++": {
                "iostream",
                "vector",
                "string",
                "map",
                "set",
                "algorithm",
                "memory",
                "fstream",
                "sstream",
                "cmath"
            },

            "C#": {
                "System"
            },

            "Dart": {
                "dart:core",
                "dart:async",
                "dart:convert",
                "dart:io",
                "dart:math"
            }
        }

    def classify(
        self,
        project_path,
        dependency_name,
        ecosystem,
        declared_dependencies=None
    ):

        declared_dependencies = declared_dependencies or set()

        # 1. Manifest says it is external
        if dependency_name in declared_dependencies:
            return "declared_external"

        # 2. Invalid / obvious non-package token
        if self.is_keyword(
            dependency_name,
            ecosystem
        ):
            return "built_in"

        # 3. Built-in library
        if self.is_builtin(
            dependency_name,
            ecosystem
        ):
            return "built_in"

        # 4. Local project dependency
        if self.is_local_dependency(
            project_path,
            dependency_name,
            ecosystem
        ):
            return "local"

        # 5. Unknown candidate
        return "undeclared_external"

    def is_keyword(
        self,
        dependency_name,
        ecosystem
    ):

        keywords = self.language_keywords.get(
            ecosystem,
            set()
        )

        return dependency_name in keywords

    def is_builtin(
        self,
        dependency_name,
        ecosystem
    ):

        builtins = self.builtin_names.get(
            ecosystem,
            set()
        )

        if dependency_name in builtins:
            return True

        # Python nested standard-library imports
        if ecosystem == "Python":
            root = dependency_name.split(".")[0]

            return root in builtins

        # Java built-in namespaces
        if ecosystem == "Java":
            root = dependency_name.split(".")[0]

            return root in builtins

        # C# built-in namespaces
        if ecosystem == "C#":
            return dependency_name == "System"

        # Dart built-in libraries
        if ecosystem == "Dart":
            return dependency_name.startswith("dart:")

        return False

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

        if ecosystem in {
            "JavaScript",
            "TypeScript"
        }:
            return (
                dependency_name.startswith(".")
                or dependency_name.startswith("/")
            )

        if ecosystem in {
            "C",
            "C++"
        }:
            return self._is_local_cpp(
                project,
                dependency_name
            )

        if ecosystem in {
            "C#",
            "Java"
        }:
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

        if ecosystem in {
            "PHP",
            "Ruby",
            "Dart"
        }:
            return (
                project / dependency_name
            ).exists()

        return False

    def _is_local_python(
        self,
        project,
        dependency
    ):

        root_name = dependency.split(".")[0]

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

                elif (
                    path.is_file()
                    and path.suffix == ".py"
                ):

                    relative = path.relative_to(
                        project
                    )

                    if path.name == "__init__.py":

                        for part in relative.parent.parts:
                            module_names.add(part)

                    else:
                        module_names.add(path.stem)

        scan(project)

        return root_name in module_names

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

    def _is_local_cpp(
        self,
        project,
        dependency
    ):

        dependency = dependency.strip(
            "<>"
        )

        return (
            (project / dependency).exists()
            or any(
                path.name == dependency
                for path in project.rglob("*")
                if path.is_file()
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