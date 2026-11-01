from pathlib import Path
import ast
import json
import re
import sys


from plugins.workspace_launcher.environment_checker import EnvironmentChecker
from plugins.workspace_launcher.dependency_classifier import DependencyClassifier
from plugins.workspace_launcher.adapters import get_adapters


class DependencyAnalyzer:
    """
    Generic dependency analyzer for Python, Node.js, JavaScript/TypeScript,
    and C#/.NET projects.

    Responsibilities:
    - Discover project files while skipping generated directories.
    - Analyze supported dependency manifests.
    - Extract imports from source files.
    - Classify dependencies without installing anything.
    - Preserve manifest versions and source locations.
    - Flag uncertain package mappings for review.
    """

    def __init__(self):
        self.name = "Dependency Analyzer"

        self.classifier = DependencyClassifier()
        self.adapters = get_adapters()
        self.environment_checker = EnvironmentChecker()

        self.skip_directories = {
            ".git",
            ".hg",
            ".svn",
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
            ".next",
            ".nuxt",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "coverage",
            ".venv.backup",
            "models",
        }

        self.source_extensions = {
            ".py": "Python",
            ".pyw": "Python",
            ".js": "JavaScript",
            ".jsx": "JavaScript",
            ".mjs": "JavaScript",
            ".cjs": "JavaScript",
            ".ts": "TypeScript",
            ".tsx": "TypeScript",
            ".mts": "TypeScript",
            ".cts": "TypeScript",
            ".cs": "C#",
            ".java": "Java",
            ".c": "C",
            ".h": "C",
            ".cpp": "C++",
            ".cc": "C++",
            ".cxx": "C++",
            ".hpp": "C++",
            ".hh": "C++",
            ".hxx": "C++",
            ".php": "PHP",
            ".rs": "Rust",
            ".go": "Go",
            ".rb": "Ruby",
            ".dart": "Dart",
        }

        self.dependency_files = {
            # Python
            "requirements.txt",
            "requirements-dev.txt",
            "pyproject.toml",
            "Pipfile",
            "setup.py",
            "setup.cfg",

            # Node.js
            "package.json",

            # C#/.NET
            "Directory.Build.props",
            "Directory.Build.targets",
            "Directory.Packages.props",

            # Other ecosystems
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

        # Python import name -> PyPI distribution name
        self.python_distribution_map = {
            "PIL": "Pillow",
            "cv2": "opencv-python",
            "sklearn": "scikit-learn",
            "yaml": "PyYAML",
            "bs4": "beautifulsoup4",
            "dotenv": "python-dotenv",
            "Crypto": "pycryptodome",
            "jwt": "PyJWT",
            "magic": "python-magic",
            "serial": "pyserial",
            "dateutil": "python-dateutil",
            "googleapiclient": "google-api-python-client",
            "grpc": "grpcio",
        }

        # Built-in Node.js modules
        self.node_builtins = {
            "assert",
            "async_hooks",
            "buffer",
            "child_process",
            "cluster",
            "console",
            "constants",
            "crypto",
            "dgram",
            "diagnostics_channel",
            "dns",
            "domain",
            "events",
            "fs",
            "http",
            "http2",
            "https",
            "module",
            "net",
            "os",
            "path",
            "path/posix",
            "path/win32",
            "perf_hooks",
            "process",
            "punycode",
            "querystring",
            "readline",
            "repl",
            "stream",
            "stream/consumers",
            "stream/promises",
            "stream/web",
            "string_decoder",
            "sys",
            "timers",
            "timers/promises",
            "tls",
            "trace_events",
            "tty",
            "url",
            "util",
            "util/types",
            "v8",
            "vm",
            "wasi",
            "worker_threads",
            "zlib",
            "test",
            "inspector",
            "sqlite",
        }

    # ---------------------------------------------------------
    # Public API
    # ---------------------------------------------------------

    def analyze(self, project_path):
        """
        Scan a project and return its source files, manifests,
        extracted imports, and manifest analysis.

        This method does not install or modify anything.
        """
        project = Path(project_path).expanduser().resolve()

        if not project.exists():
            return {
                "status": "error",
                "message": f"Project path does not exist: {project}",
                "project_path": str(project),
                "dependency_files": [],
                "source_files": [],
                "languages": {},
                "imports": {},
                "manifest_analysis": [],
            }

        if not project.is_dir():
            return {
                "status": "error",
                "message": f"Project path is not a directory: {project}",
                "project_path": str(project),
                "dependency_files": [],
                "source_files": [],
                "languages": {},
                "imports": {},
                "manifest_analysis": [],
            }

        discovered_files = self._discover_files(project)

        dependency_files = []
        source_files = []
        languages = {}
        imports = {}

        for file_path in discovered_files:
            # Manifest files should not be treated as source code.
            if self._is_dependency_file(file_path):
                dependency_files.append(file_path)
                continue

            language = self.source_extensions.get(
                file_path.suffix.lower()
            )

            if not language:
                continue

            source_files.append(file_path)

            languages.setdefault(language, 0)
            languages[language] += 1

            extracted = self.extract_imports(file_path, language)

            if extracted:
                imports[str(file_path)] = extracted

        manifest_analysis = self.analyze_manifests(dependency_files)

        return {
            "status": "success",
            "project_path": str(project),
            "dependency_files": [
                str(path) for path in dependency_files
            ],
            "source_files": [
                str(path) for path in source_files
            ],
            "languages": languages,
            "imports": imports,
            "manifest_analysis": manifest_analysis,
        }

    def resolve_dependencies(self, project_path, analysis=None):
        """
        Combine manifest declarations and source imports.

        Returns dependency records suitable for a review/install-planning
        stage. This method does not install packages.

        Important:
        - An import is not automatically proof of an installable package.
        - Unknown mappings are marked needs_review.
        - Manifest version constraints are preserved when available.
        """
        if analysis is None:
            analysis = self.analyze(project_path)

        if analysis["status"] != "success":
            return []

        dependencies = {}

        manifest_records = analysis["manifest_analysis"]

        # Keep declared dependencies grouped by ecosystem.
        declared_by_ecosystem = {}

        for manifest in manifest_records:
            ecosystem = self._canonical_ecosystem(
                manifest.get("ecosystem")
            )

            declared_by_ecosystem.setdefault(ecosystem, [])

            for item in manifest.get("external", []):
                if not isinstance(item, dict):
                    continue

                name = item.get("name")

                if not name:
                    continue

                version = item.get("version")
                package_name = str(name).strip()

                key = self._dependency_key(
                    ecosystem,
                    package_name,
                )

                if key not in dependencies:
                    dependencies[key] = {
                        "name": package_name,
                        "ecosystem": ecosystem,
                        "version": version,
                        "source": [],
                        "classification": "declared_external",
                        "needs_review": False,
                        "review_reason": None,
                    }

                elif (
                    version
                    and not dependencies[key].get("version")
                ):
                    dependencies[key]["version"] = version

                manifest_file = manifest.get("file")

                if manifest_file:
                    self._append_unique(
                        dependencies[key]["source"],
                        manifest_file,
                    )

                declared_by_ecosystem[ecosystem].append({
                    "name": package_name,
                    "version": version,
                    "key": key,
                })

        # Process imports independently of whether a manifest exists.
        # This prevents undeclared source dependencies from being hidden.
        for file_path, imported_names in analysis["imports"].items():
            path = Path(file_path)

            language = self.source_extensions.get(
                path.suffix.lower()
            )

            if not language:
                continue

            ecosystem = self._canonical_ecosystem(language)

            declarations = declared_by_ecosystem.get(
                ecosystem,
                [],
            )

            for import_name in imported_names:
                if not import_name:
                    continue

                resolution = self._resolve_import(
                    project_path=Path(analysis["project_path"]),
                    import_name=import_name,
                    language=language,
                    declarations=declarations,
                )

                # Built-ins and local imports are not external packages.
                if resolution["classification"] in {
                    "built_in",
                    "local",
                }:
                    continue

                package_name = resolution.get("name")

                if not package_name:
                    continue

                key = self._dependency_key(
                    ecosystem,
                    package_name,
                )

                if key in dependencies:
                    self._append_unique(
                        dependencies[key]["source"],
                        file_path,
                    )

                    # A declaration found in a manifest takes precedence.
                    continue

                classification = resolution["classification"]

                dependencies[key] = {
                    "name": package_name,
                    "ecosystem": ecosystem,
                    "version": resolution.get("version"),
                    "source": [file_path],
                    "classification": classification,
                    "needs_review": resolution.get(
                        "needs_review",
                        False,
                    ),
                    "review_reason": resolution.get(
                        "review_reason"
                    ),
                }

        return sorted(
            dependencies.values(),
            key=lambda item: (
                item.get("ecosystem") or "",
                item.get("name") or "",
            ),
        )

    # ---------------------------------------------------------
    # File discovery
    # ---------------------------------------------------------

    def _discover_files(self, project):
        files = []
        self._scan_directory(project, files)
        return sorted(files)

    def _scan_directory(self, directory, results):
        try:
            entries = list(directory.iterdir())
        except (PermissionError, OSError):
            return

        for entry in entries:
            try:
                if entry.is_symlink():
                    continue

                if entry.is_dir():
                    if entry.name in self.skip_directories:
                        continue

                    self._scan_directory(entry, results)

                elif entry.is_file():
                    results.append(entry)

            except (PermissionError, OSError):
                continue

    def _is_dependency_file(self, file_path):
        if file_path.name in self.dependency_files:
            return True

        # Let the registered adapters identify supported manifests,
        # including .csproj, .fsproj, .sln, .slnx and similar files.
        for adapter in self.adapters:
            try:
                if adapter.can_handle(file_path):
                    return True
            except Exception:
                continue

        return False

    # ---------------------------------------------------------
    # Manifest analysis
    # ---------------------------------------------------------

    def analyze_manifests(self, dependency_files):
        results = []

        for file_path in dependency_files:
            for adapter in self.adapters:
                try:
                    if adapter.can_handle(file_path):
                        result = adapter.analyze_manifest(file_path)

                        if not isinstance(result, dict):
                            break

                        result.setdefault(
                            "file",
                            str(file_path),
                        )

                        result.setdefault(
                            "external",
                            [],
                        )

                        result.setdefault(
                            "local",
                            [],
                        )

                        results.append(result)
                        break

                except Exception as exc:
                    results.append({
                        "ecosystem": "Unknown",
                        "file": str(file_path),
                        "runtime": None,
                        "sdk": None,
                        "external": [],
                        "local": [],
                        "errors": [
                            f"Manifest analysis failed: {exc}"
                        ],
                    })

                    break

        return results

    # ---------------------------------------------------------
    # Import extraction
    # ---------------------------------------------------------

    def extract_imports(self, file_path, language):
        text = self._read_text(file_path)

        if text is None:
            return []

        try:
            if language == "Python":
                return self._extract_python_imports(text)

            if language in {"JavaScript", "TypeScript"}:
                return self._extract_javascript_imports(text)

            if language == "C#":
                return self._extract_csharp_imports(text)

            if language == "Java":
                return self._extract_java_imports(text)

            if language in {"C", "C++"}:
                return self._extract_cpp_imports(text)

            if language == "PHP":
                return self._extract_php_imports(text)

            if language == "Rust":
                return self._extract_rust_imports(text)

            if language == "Go":
                return self._extract_go_imports(text)

            if language == "Ruby":
                return self._extract_ruby_imports(text)

            if language == "Dart":
                return self._extract_dart_imports(text)

        except Exception:
            # A single malformed source file should not abort the scan.
            return []

        return []

    def _extract_python_imports(self, text):
        imports = set()

        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]

                    if root:
                        imports.add(root)

            elif isinstance(node, ast.ImportFrom):
                # Relative imports are local project imports.
                if node.level > 0:
                    continue

                if node.module:
                    root = node.module.split(".")[0]

                    if root:
                        imports.add(root)

        return sorted(imports)

    def _extract_javascript_imports(self, text):
        imports = set()

        # Remove comments before matching to reduce false positives.
        cleaned = self._remove_js_comments(text)

        patterns = [
            r"""(?:import|export)\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]""",
            r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""",
            r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)""",
        ]

        for pattern in patterns:
            for match in re.findall(pattern, cleaned):
                package = self._normalise_js_import(match)

                if package:
                    imports.add(package)

        return sorted(imports)

    def _remove_js_comments(self, text):
        """
        Remove common JavaScript/TypeScript comments.

        This intentionally avoids a full parser; imports inside unusual
        strings or template literals can still require manual review.
        """
        text = re.sub(
            r"/\*.*?\*/",
            "",
            text,
            flags=re.DOTALL,
        )

        text = re.sub(
            r"^\s*//.*$",
            "",
            text,
            flags=re.MULTILINE,
        )

        return text

    def _normalise_js_import(self, module_name):
        module_name = module_name.strip()

        if not module_name:
            return None

        # Relative imports are local files.
        if module_name.startswith((".", "/", "\\")):
            return None

        # URLs are not npm package dependencies.
        if module_name.startswith(("http://", "https://", "data:")):
            return None

        # node:fs and similar imports refer to Node.js built-ins.
        if module_name.startswith("node:"):
            return module_name

        # Scoped package: @scope/package/subpath -> @scope/package
        if module_name.startswith("@"):
            parts = module_name.split("/")

            if len(parts) >= 2:
                return "/".join(parts[:2])

            return module_name

        # Normal package: package/subpath -> package
        return module_name.split("/")[0]

    def _extract_csharp_imports(self, text):
        imports = set()

        # Supports:
        # using System;
        # global using Microsoft.Extensions.Logging;
        # using static Some.Namespace.SomeClass;
        # using Alias = Some.Namespace;
        pattern = (
            r"^\s*(?:global\s+)?using\s+"
            r"(?:static\s+)?"
            r"(?:[A-Za-z_]\w*\s*=\s*)?"
            r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;"
        )

        for match in re.findall(
            pattern,
            text,
            flags=re.MULTILINE,
        ):
            imports.add(match.strip())

        return sorted(imports)

    def _extract_java_imports(self, text):
        imports = set()

        pattern = (
            r"^\s*import\s+"
            r"(?:static\s+)?"
            r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)"
            r"(?:\.\*)?\s*;"
        )

        for match in re.findall(
            pattern,
            text,
            flags=re.MULTILINE,
        ):
            parts = match.split(".")

            if parts:
                imports.add(".".join(parts[:2]))

        return sorted(imports)

    def _extract_cpp_imports(self, text):
        imports = set()

        for match in re.findall(
            r'^\s*#\s*include\s*[<"]([^>"]+)[>"]',
            text,
            flags=re.MULTILINE,
        ):
            imports.add(match.strip())

        return sorted(imports)

    def _extract_php_imports(self, text):
        imports = set()

        for match in re.findall(
            r"^\s*use\s+([A-Za-z_\\][A-Za-z0-9_\\]*)",
            text,
            flags=re.MULTILINE,
        ):
            imports.add(match.lstrip("\\"))

        return sorted(imports)

    def _extract_rust_imports(self, text):
        imports = set()

        for match in re.findall(
            r"^\s*use\s+([A-Za-z_][A-Za-z0-9_]*)",
            text,
            flags=re.MULTILINE,
        ):
            imports.add(match)

        return sorted(imports)

    def _extract_go_imports(self, text):
        imports = set()

        # Handles both single imports and common import blocks.
        pattern = r'"([^"]+)"'

        in_import_block = False

        for line in text.splitlines():
            stripped = line.strip()

            if stripped.startswith("import ("):
                in_import_block = True
                continue

            if in_import_block:
                if stripped == ")":
                    in_import_block = False
                    continue

                match = re.search(pattern, stripped)

                if match:
                    imports.add(match.group(1))

                continue

            if stripped.startswith("import "):
                match = re.search(pattern, stripped)

                if match:
                    imports.add(match.group(1))

        return sorted(imports)

    def _extract_ruby_imports(self, text):
        imports = set()

        for match in re.findall(
            r"""^\s*require(?:_relative)?\s*['"]([^'"]+)['"]""",
            text,
            flags=re.MULTILINE,
        ):
            imports.add(match)

        return sorted(imports)

    def _extract_dart_imports(self, text):
        imports = set()

        for match in re.findall(
            r"""^\s*import\s+['"]([^'"]+)['"]""",
            text,
            flags=re.MULTILINE,
        ):
            imports.add(match)

        return sorted(imports)

    # ---------------------------------------------------------
    # Dependency resolution and classification
    # ---------------------------------------------------------

    def _resolve_import(
        self,
        project_path,
        import_name,
        language,
        declarations,
    ):
        """
        Convert an import into a best-effort dependency record.

        This function does not query package registries or install anything.
        """
        ecosystem = self._canonical_ecosystem(language)

        # Python
        if language == "Python":
            # Standard-library modules
            if import_name in sys.stdlib_module_names:
                return {
                    "name": import_name,
                    "classification": "built_in",
                }

            # Convert Python import names to PyPI distribution names
            distribution_name = self.python_distribution_map.get(
                import_name,
                import_name,
            )

            # Check whether the dependency is declared in a manifest
            declared = self._find_declared_package(
                distribution_name,
                declarations,
            )

            if declared:
                return {
                    "name": declared["name"],
                    "version": declared.get("version"),
                    "classification": "declared_external",
                }

            # Check whether this import belongs to the project itself
            if self._is_local_python_import(
                project_path,
                import_name,
            ):
                return {
                    "name": import_name,
                    "classification": "local",
                }

            # Treat the remaining imports as external dependencies
            known_mapping = import_name in self.python_distribution_map

            return {
                "name": distribution_name,
                "classification": "undeclared_external",
                "needs_review": not known_mapping,
                "review_reason": (
                    None
                    if known_mapping
                    else (
                        "Python import names do not always match PyPI "
                        "distribution names. Verify the package mapping."
                    )
                ),
            }

    # Keep your existing code for other languages below this point.

        # JavaScript and TypeScript
        if language in {"JavaScript", "TypeScript"}:
            module_name = self._normalise_js_import(import_name)

            if not module_name:
                return {
                    "name": import_name,
                    "classification": "local",
                }

            builtin_name = module_name.removeprefix("node:")

            if (
                import_name.startswith("node:")
                or builtin_name in self.node_builtins
            ):
                return {
                    "name": module_name,
                    "classification": "built_in",
                }

            declared = self._find_declared_package(
                module_name,
                declarations,
            )

            if declared:
                return {
                    "name": declared["name"],
                    "version": declared.get("version"),
                    "classification": "declared_external",
                }

            classification = self._safe_classify(
                project_path,
                module_name,
                language,
                declarations,
            )

            if classification == "local":
                return {
                    "name": module_name,
                    "classification": "local",
                }

            return {
                "name": module_name,
                "classification": "undeclared_external",
                "needs_review": True,
                "review_reason": (
                    "Verify that this import is an npm package and not "
                    "an alias, generated module, or workspace dependency."
                ),
            }

        # C#/.NET
        if language == "C#":
            # Prefer matching a namespace to an actual declared NuGet
            # package, rather than assuming namespace == package name.
            declared = self._match_dotnet_namespace(
                import_name,
                declarations,
            )

            if declared:
                return {
                    "name": declared["name"],
                    "version": declared.get("version"),
                    "classification": "declared_external",
                }

            classification = self._safe_classify(
                project_path,
                import_name,
                language,
                declarations,
            )

            if classification in {"built_in", "local"}:
                return {
                    "name": import_name,
                    "classification": classification,
                }

            return {
                "name": import_name,
                "classification": "undeclared_external",
                "needs_review": True,
                "review_reason": (
                    "A C# namespace is not necessarily a NuGet package "
                    "name. Inspect project references and package metadata."
                ),
            }

        # Other supported languages: classify conservatively.
        classification = self._safe_classify(
            project_path,
            import_name,
            language,
            declarations,
        )

        if classification in {"built_in", "local"}:
            return {
                "name": import_name,
                "classification": classification,
            }

        return {
            "name": import_name,
            "classification": "undeclared_external",
            "needs_review": True,
            "review_reason": (
                f"Automatic package-name resolution is not yet implemented "
                f"for {language}. Verify the dependency before installation."
            ),
        }

    def _safe_classify(
        self,
        project_path,
        import_name,
        language,
        declarations,
    ):
        """
        Use the existing DependencyClassifier without allowing a classifier
        error to abort the full scan.
        """
        try:
            result = self.classifier.classify(
                project_path,
                import_name,
                language,
                {
                    item["name"]
                    for item in declarations
                    if item.get("name")
                },
            )

            if result:
                return result

        except Exception:
            pass

        return "undeclared_external"
    

    

    def _match_dotnet_namespace(self, namespace, declarations):
        """
        Match a C# namespace to a declared NuGet package when evidence exists.

        Example:
            namespace: Google.Cloud.Firestore
            declared package: Google.Cloud.Firestore

        The match is based on existing manifest declarations, not a
        hardcoded assumption that every namespace root is a package.
        """
        namespace = namespace.strip().strip(".")

        if not namespace:
            return None

        matches = []

        for declaration in declarations:
            package_name = declaration.get("name", "").strip()

            if not package_name:
                continue

            if (
                namespace == package_name
                or namespace.startswith(package_name + ".")
                or package_name.startswith(namespace + ".")
            ):
                matches.append(declaration)

        if not matches:
            return None

        # Prefer the most specific package-name match.
        return max(
            matches,
            key=lambda item: len(item.get("name", "")),
        )

    def _find_declared_package(self, import_name, declarations):
        """
        Match an import to a declared package using normalized names.

        This is a best-effort comparison. It does not guarantee that an
        arbitrary import name maps to the same-named package.
        """
        target = self._normalise_package_name(import_name)

        for declaration in declarations:
            declared_name = declaration.get("name")

            if not declared_name:
                continue

            if self._normalise_package_name(declared_name) == target:
                return declaration

        return None

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------

    def _canonical_ecosystem(self, name):
        """
        Normalize source-language and manifest ecosystem labels.

        Keep source language labels separate when calling the classifier.
        """
        mapping = {
            "Python": "Python",
            "JavaScript": "Node.js",
            "TypeScript": "Node.js",
            "Node.js": "Node.js",
            "C#": ".NET",
            ".NET": ".NET",
            "Java": "Java",
            "C": "C",
            "C++": "C++",
            "PHP": "PHP",
            "Rust": "Rust",
            "Go": "Go",
            "Ruby": "Ruby",
            "Dart": "Dart",
        }

        return mapping.get(name, name or "Unknown")

    def _dependency_key(self, ecosystem, package_name):
        normalized = self._normalise_package_name(package_name)

        return f"{ecosystem.lower()}::{normalized}"

    def _normalise_package_name(self, name):
        """
        Normalize names for comparison without changing the displayed name.
        """
        return re.sub(
            r"[-_.]+",
            "-",
            str(name).strip().lower(),
        )

    def _append_unique(self, items, value):
        if value and value not in items:
            items.append(value)

    def _read_text(self, file_path):
        try:
            return Path(file_path).read_text(
                encoding="utf-8",
                errors="replace",
            )
        except (OSError, PermissionError):
            return None
    


    def analyze_and_verify(self, project_path):
        """Analyze dependencies and verify the project environment."""

        analysis = self.analyze(project_path)

        if analysis["status"] != "success":
            return {
                "status": "error",
                "message": analysis.get(
                    "message",
                    "Project analysis failed."
                ),
                "analysis": analysis,
            }

        dependencies = self.resolve_dependencies(
            project_path,
            analysis=analysis,
        )

        verification = self.environment_checker.verify_dependencies(
            project_path,
            dependencies,
        )

        return {
            "status": "success",
            "project_path": analysis["project_path"],
            "languages": analysis["languages"],
            "dependency_files": analysis["dependency_files"],
            "source_files": analysis["source_files"],
            "dependencies": verification.get("dependencies", []),
            "environment": verification.get("environment", {}),
            "summary": verification.get("summary", {}),
            "verification_status": verification.get("status"),
            "verification_message": verification.get("message"),
        }


    def _is_local_python_import(self, project_path, import_name):
        """
        Check whether a Python import belongs to the project itself.
        """
        project = Path(project_path).expanduser().resolve()
        module_name = str(import_name).split(".")[0]

        if not module_name or not module_name.isidentifier():
            return False

        search_dirs = {project}

        # Find directories containing Python source files
        for file_path in self._discover_files(project):
            if file_path.suffix.lower() in {".py", ".pyw"}:
                search_dirs.add(file_path.parent)

        for directory in search_dirs:
            # Example: backend/utils.py
            module_file = directory / f"{module_name}.py"

            if module_file.is_file():
                return True

            # Example: backend/utils/__init__.py
            package_dir = directory / module_name

            if not package_dir.is_dir():
                continue

            if (package_dir / "__init__.py").is_file():
                return True

            # Support namespace packages without __init__.py
            for child in self._discover_files(package_dir):
                if child.suffix.lower() in {".py", ".pyw"}:
                    return True

        return False