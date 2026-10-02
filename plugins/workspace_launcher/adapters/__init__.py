from plugins.workspace_launcher.adapters.csharp import CSharpAdapter


def get_adapters():
    return [
        CSharpAdapter()
    ]