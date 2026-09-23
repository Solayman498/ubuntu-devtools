from core.plugin_manager import PluginManager
from plugins.port_manager import PortManager


def main():
    plugin_manager = PluginManager()

    port_manager = PortManager()
    plugin_manager.register_plugin(port_manager)

    print("Ubuntu DevTools started")
    print("Plugins:")

    for plugin in plugin_manager.get_plugins():
        print("-", plugin.get_name())


if __name__ == "__main__":
    main()