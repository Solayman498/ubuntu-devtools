from pathlib import Path
import ast
import re
import sys
from plugins.workspace_launcher.dependency_classifier import DependencyClassifier
from plugins.workspace_launcher.adapters import get_adapters


class DependencyAnalyzer:

    def __init__(self):
        self.name = "Dependency Analyzer"
        self.classifier = DependencyClassifier()
        self.adapters = get_adapters()

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

        self.source_extensions = {
            ".py": "Python",
            ".js": "JavaScript",
            ".jsx": "JavaScript",
            ".ts": "TypeScript",
            ".tsx": "TypeScript",
            ".java": "Java",
            ".c": "C",
            ".h": "C",
            ".cpp": "C++",
            ".cc": "C++",
            ".cxx": "C++",
            ".hpp": "C++",
            ".cs": "C#",
            ".php": "PHP",
            ".rs": "Rust",
            ".go": "Go",
            ".rb": "Ruby",
            ".dart": "Dart",
        }

        self.dependency_files = {
            "requirements.txt",
            "pyproject.toml",
            "Pipfile",
            "package.json",
            "composer.json",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "Cargo.toml",
            "go.mod",
            "Gemfile",
            "pubspec.yaml",
            "CMakeLists.txt",
            "Makefile",
        }

    # --------------------------------------------------
    # Main analyzer
    # --------------------------------------------------

    def analyze(self, project_path):

        project = Path(project_path)

        if not project.exists() or not project.is_dir():
            return {
                "status": "Error",
                "dependency_files": [],
                "source_files": [],
                "languages": {},
                "imports": {}
            }

        files = self._discover_files(project)

        dependency_files = []
        source_files = []
        languages = {}
        imports = {}

        for file in files:

            if (
                file.name in self.dependency_files
                or any(
                    adapter.can_handle(file)
                    for adapter in self.adapters
                )
            ):
                dependency_files.append(str(file))

            elif file.suffix.lower() in self.source_extensions:

                language = self.source_extensions[
                    file.suffix.lower()
                ]

                source_files.append(str(file))

                languages.setdefault(
                    language,
                    []
                ).append(str(file))

                detected_imports = self.extract_imports(
                    file
                )

                if detected_imports:
                    imports[str(file)] = detected_imports

        manifest_analysis = self.analyze_manifests(
            dependency_files
        )

        return {
            "status": "Analyzed",
            "dependency_files": dependency_files,
            "source_files": source_files,
            "languages": languages,
            "imports": imports,
            "manifest_analysis": manifest_analysis
        }

    # --------------------------------------------------
    # File discovery
    # --------------------------------------------------

    def _discover_files(self, project):

        discovered_files = []

        self._scan_directory(
            project,
            discovered_files
        )

        return discovered_files

    def _scan_directory(
        self,
        directory,
        discovered_files
    ):

        try:
            children = directory.iterdir()
        except (PermissionError, OSError):
            return

        for child in children:

            if child.is_symlink():
                continue

            if child.is_dir():

                if child.name in self.skip_directories:
                    continue

                self._scan_directory(
                    child,
                    discovered_files
                )

            elif child.is_file():

                discovered_files.append(child)

    # --------------------------------------------------
    # Language dispatcher
    # --------------------------------------------------

    def extract_imports(self, file_path):

        path = Path(file_path)
        extension = path.suffix.lower()

        if extension == ".py":
            return self.extract_python_imports(file_path)

        if extension in {".js", ".jsx", ".ts", ".tsx"}:
            return self.extract_javascript_imports(file_path)

        if extension == ".java":
            return self.extract_java_imports(file_path)

        if extension in {
            ".c",
            ".h",
            ".cpp",
            ".cc",
            ".cxx",
            ".hpp"
        }:
            return self.extract_cpp_imports(file_path)

        if extension == ".cs":
            return self.extract_csharp_imports(file_path)

        if extension == ".php":
            return self.extract_php_imports(file_path)

        if extension == ".rs":
            return self.extract_rust_imports(file_path)

        if extension == ".go":
            return self.extract_go_imports(file_path)

        if extension == ".rb":
            return self.extract_ruby_imports(file_path)

        if extension == ".dart":
            return self.extract_dart_imports(file_path)

        return []

    # --------------------------------------------------
    # Python
    # --------------------------------------------------

    def extract_python_imports(self, file_path):

        imports = set()

        try:
            with open(
                file_path,
                "r",
                encoding="utf-8"
            ) as file:

                source = file.read()

            tree = ast.parse(source)

            for node in ast.walk(tree):

                if isinstance(node, ast.Import):

                    for alias in node.names:
                        imports.add(
                            alias.name.split(".")[0]
                        )

                elif isinstance(node, ast.ImportFrom):

                    if node.module:
                        imports.add(
                            node.module.split(".")[0]
                        )

        except (
            OSError,
            UnicodeDecodeError,
            SyntaxError
        ):
            return []

        return sorted(imports)

    # --------------------------------------------------
    # JavaScript / TypeScript
    # --------------------------------------------------

    def extract_javascript_imports(self, file_path):

        imports = set()

        content = self._read_text(file_path)

        if content is None:
            return []

        patterns = [
            r'import\s+(?:.*?\s+from\s+)?[\'"]([^\'"]+)[\'"]',
            r'require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)',
            r'import\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)'
        ]

        for pattern in patterns:

            matches = re.findall(
                pattern,
                content
            )

            for match in matches:

                if match.startswith("."):
                    continue

                package = match.split("/")[0]

                if match.startswith("@"):
                    parts = match.split("/")

                    if len(parts) >= 2:
                        package = (
                            parts[0] + "/" + parts[1]
                        )

                imports.add(package)

        return sorted(imports)

    # --------------------------------------------------
    # Java
    # --------------------------------------------------

    def extract_java_imports(self, file_path):

        imports = set()

        content = self._read_text(file_path)

        if content is None:
            return []

        matches = re.findall(
            r'^\s*import\s+(?:static\s+)?([a-zA-Z0-9_.]+)',
            content,
            re.MULTILINE
        )

        for match in matches:
            imports.add(
                match.split(".")[0]
            )

        return sorted(imports)

    # --------------------------------------------------
    # C / C++
    # --------------------------------------------------

    def extract_cpp_imports(self, file_path):

        imports = set()

        content = self._read_text(file_path)

        if content is None:
            return []

        matches = re.findall(
            r'#include\s*[<"]([^>"]+)[>"]',
            content
        )

        for match in matches:

            # Local project header
            if "/" in match:
                imports.add(match)

            else:
                imports.add(match)

        return sorted(imports)

    # --------------------------------------------------
    # C#
    # --------------------------------------------------

    def extract_csharp_imports(self, file_path):

        imports = set()

        content = self._read_text(file_path)

        if content is None:
            return []

        matches = re.findall(
            r'^\s*using\s+([a-zA-Z0-9_.]+)',
            content,
            re.MULTILINE
        )

        for match in matches:
            imports.add(match.split(".")[0])

        return sorted(imports)

    # --------------------------------------------------
    # PHP
    # --------------------------------------------------

    def extract_php_imports(self, file_path):

        imports = set()

        content = self._read_text(file_path)

        if content is None:
            return []

        use_matches = re.findall(
            r'^\s*use\s+([^;]+);',
            content,
            re.MULTILINE
        )

        require_matches = re.findall(
            r'(?:require|require_once|include|include_once)'
            r'\s*[\'"]([^\'"]+)[\'"]',
            content
        )

        for match in use_matches:
            imports.add(
                match.strip().split("\\")[0]
            )

        for match in require_matches:
            imports.add(match)

        return sorted(imports)

    # --------------------------------------------------
    # Rust
    # --------------------------------------------------

    def extract_rust_imports(self, file_path):

        imports = set()

        content = self._read_text(file_path)

        if content is None:
            return []

        use_matches = re.findall(
            r'^\s*use\s+([a-zA-Z0-9_]+)',
            content,
            re.MULTILINE
        )

        extern_matches = re.findall(
            r'^\s*extern\s+crate\s+([a-zA-Z0-9_]+)',
            content,
            re.MULTILINE
        )

        imports.update(use_matches)
        imports.update(extern_matches)

        return sorted(imports)

    # --------------------------------------------------
    # Go
    # --------------------------------------------------

    def extract_go_imports(self, file_path):

        imports = set()

        content = self._read_text(file_path)

        if content is None:
            return []

        single_matches = re.findall(
            r'import\s+"([^"]+)"',
            content
        )

        block_matches = re.findall(
            r'import\s*\((.*?)\)',
            content,
            re.DOTALL
        )

        imports.update(single_matches)

        for block in block_matches:

            paths = re.findall(
                r'"([^"]+)"',
                block
            )

            imports.update(paths)

        return sorted(imports)

    # --------------------------------------------------
    # Ruby
    # --------------------------------------------------

    def extract_ruby_imports(self, file_path):

        imports = set()

        content = self._read_text(file_path)

        if content is None:
            return []

        matches = re.findall(
            r'^\s*require\s+[\'"]([^\'"]+)[\'"]',
            content,
            re.MULTILINE
        )

        imports.update(matches)

        return sorted(imports)

    # --------------------------------------------------
    # Dart
    # --------------------------------------------------

    def extract_dart_imports(self, file_path):

        imports = set()

        content = self._read_text(file_path)

        if content is None:
            return []

        matches = re.findall(
            r'^\s*(?:import|export)\s+[\'"]([^\'"]+)[\'"]',
            content,
            re.MULTILINE
        )

        for match in matches:

            if match.startswith("dart:"):
                imports.add(match)

            elif match.startswith("package:"):

                parts = match.split("/")

                if len(parts) >= 2:
                    imports.add(
                        parts[1]
                    )

            elif not match.startswith("."):
                imports.add(match)

        return sorted(imports)

    # --------------------------------------------------
    # Utility
    # --------------------------------------------------

    def _read_text(self, file_path):

        try:
            with open(
                file_path,
                "r",
                encoding="utf-8"
            ) as file:

                return file.read()

        except (
            OSError,
            UnicodeDecodeError
        ):
            return None

    # --------------------------------------------------
    # Python standard library separation
    # --------------------------------------------------

    def separate_python_dependencies(self, imports):

        built_in = []
        external = []

        for package in imports:

            if package in sys.stdlib_module_names:
                built_in.append(package)

            else:
                external.append(package)

        return {
            "built_in": sorted(built_in),
            "external": sorted(external)
        }
    
    def resolve_dependencies(self, project_path):

        analysis = self.analyze(project_path)

        dependencies = {}

        # Dependencies declared by project manifests
                
        declared_dependencies = set()

        for manifest in analysis["manifest_analysis"]:

            for dependency in manifest["external"]:

                name = dependency["name"]

                declared_dependencies.add(name)

                dependencies.setdefault(
                    name,
                    {
                        "name": name,
                        "ecosystem": manifest["ecosystem"],
                        "version": dependency["version"],
                        "source": [],
                        "classification": "declared_external"
                    }
                )

                dependencies[name]["source"].append(
                    manifest["file"]
                )

        # Dependencies discovered from source code
        for file_path, imports in analysis["imports"].items():

            language = self.source_extensions.get(
                Path(file_path).suffix.lower()
            )

            for package in imports:

                classification = self.classifier.classify(
                    project_path,
                    package,
                    language,
                    declared_dependencies
                )

                # Ignore built-in and local modules
                if classification in {
                    "built_in",
                    "local"
                }:
                    continue

                if package not in dependencies:

                    dependencies[package] = {
                        "name": package,
                        "ecosystem": language,
                        "source": [],
                        "classification": classification
                    }

                dependencies[package]["source"].append(
                    file_path
                )

        return list(dependencies.values())

    def _read_manifest(self, file_path):

        path = Path(file_path)

        if path.name == "requirements.txt":
            return self._parse_requirements(path)

        if path.name == "package.json":
            return self._parse_package_json(path)

        return []

    def _parse_requirements(self, path):

        dependencies = []

        content = self._read_text(path)

        if content is None:
            return dependencies

        for line in content.splitlines():

            line = line.strip()

            if not line:
                continue

            if line.startswith("#"):
                continue

            # Remove common version operators
            match = re.match(
                r"^([A-Za-z0-9_.-]+)",
                line
            )

            if not match:
                continue

            package = match.group(1)

            dependencies.append({
                "name": package,
                "ecosystem": "Python",
                "source": "requirements.txt"
            })

        return dependencies

    def _parse_package_json(self, path):

        import json

        dependencies = []

        content = self._read_text(path)

        if content is None:
            return dependencies

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return dependencies

        package_sections = [
            "dependencies",
            "devDependencies"
        ]

        for section in package_sections:

            packages = data.get(
                section,
                {}
            )

            for package in packages:

                dependencies.append({
                    "name": package,
                    "ecosystem": "Node.js",
                    "source": "package.json"
                })
        return dependencies
    
    def analyze_manifests(self, dependency_files):

        results = []

        for file_path in dependency_files:

            for adapter in self.adapters:

                if not adapter.can_handle(file_path):
                    continue

                result = adapter.analyze_manifest(
                    file_path
                )

                results.append(result)

                break

        return results
        