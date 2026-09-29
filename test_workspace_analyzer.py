from plugins.workspace_launcher.workspace_analyzer import WorkspaceAnalyzer

workspace = WorkspaceAnalyzer()

results = workspace.analyze_registered_projects("/home")

for result in results:
    print("\nProject:", result["name"])

    for dependency in result["dependencies"]:
        print(
            dependency["name"],
            "→",
            dependency["classification"]
        )