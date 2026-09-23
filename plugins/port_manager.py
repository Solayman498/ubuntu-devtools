import psutil


class PortManager:
    def __init__(self):
        self.name = "Port Manager"

    def get_name(self):
        return self.name

    def get_active_ports(self):
        connections = psutil.net_connections(kind="inet")

        ports = []

        for connection in connections:
            if connection.status != "LISTEN":
                continue

            pid = connection.pid
            process_name = "Unknown"

            if pid is not None:
                try:
                    process_name = psutil.Process(pid).name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    process_name = "Unknown"

            port_info = {
                "port": connection.laddr.port,
                "pid": pid,
                "process": process_name
            }

            if port_info not in ports:
                ports.append(port_info)

        return sorted(ports, key=lambda x: x["port"])