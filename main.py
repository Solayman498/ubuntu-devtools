from core.plugin_manager import PluginManager


def main():
    plugin_manager = PluginManager()

    print("Ubuntu DevTools started")
    print("Plugins:", plugin_manager.get_plugins())


if __name__ == "__main__":
    main()