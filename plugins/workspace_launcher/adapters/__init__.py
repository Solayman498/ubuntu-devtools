from plugins.workspace_launcher.adapters.dotnet import DotNetAdapter
from plugins.workspace_launcher.adapters.python import PythonAdapter
from plugins.workspace_launcher.adapters.node import NodeAdapter


def get_adapters():
    return [
        DotNetAdapter(),
        PythonAdapter(),
        NodeAdapter(),
    ]