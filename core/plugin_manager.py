class PluginManager:

    def __init__(self):
        self.plugins = []

    def register_plugin(self, plugin):
        self.plugins.append(plugin)

    def get_plugins(self):
        return self.plugins