from plugins.workspace_launcher.adapters.csharp import CSharpAdapter
from plugins.workspace_launcher.adapters.python import PythonAdapter
from plugins.workspace_launcher.adapters.node import NodeAdapter


def get_adapters():

    return [
        CSharpAdapter(),
        PythonAdapter(),
        NodeAdapter()
    ]