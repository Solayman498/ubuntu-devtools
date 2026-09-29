from plugins.workspace_launcher.discovery import ProjectDiscovery
from plugins.workspace_launcher.analyzer import DependencyAnalyzer


class WorkspaceAnalyzer:

    def __init__(self):
        self.discovery = ProjectDiscovery()
        self.analyzer = DependencyAnalyzer()

    def analyze_registered_projects(self, root_path="/home"):

        # Step 1: Discover projects
        projects = self.discovery.discover_and_register(root_path)

        results = []

        # Step 2: Analyze every detected project
        for project in projects:

            dependencies = self.analyzer.resolve_dependencies(
                project["path"]
            )

            result = {
                "name": project["name"],
                "path": project["path"],
                "type": project["type"],
                "confidence": project["confidence"],
                "dependencies": dependencies
            }

            results.append(result)

        return results