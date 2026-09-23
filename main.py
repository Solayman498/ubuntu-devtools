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

    print("\nActive Listening Ports:")

    active_ports = port_manager.get_active_ports()

    for port_info in active_ports:
        print(
            f"- Port: {port_info['port']} | "
            f"PID: {port_info['pid']} | "
            f"Process: {port_info['process']}"
        )


if __name__ == "__main__":
    main()