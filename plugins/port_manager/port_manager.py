import psutil
import socket

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

            protocol = "TCP"

            if connection.type == socket.SOCK_DGRAM:
                protocol = "UDP"

            port_info = {
                "port": connection.laddr.port,
                "address": connection.laddr.ip,
                "protocol": protocol,
                "status": connection.status,
                "pid": pid,
                "process": process_name
            }

            if port_info not in ports:
                ports.append(port_info)

        return sorted(ports, key=lambda x: x["port"])
    
    def refresh(self):
        return self.get_active_ports()
    
    def find_port(self, port_number):
        active_ports = self.get_active_ports()

        for port_info in active_ports:
            if port_info["port"] == port_number:
                return port_info

        return None
    
    def get_process_details(self, pid):
        if pid is None:
            return None

        try:
            process = psutil.Process(pid)

            return {
                "pid": process.pid,
                "name": process.name(),
                "status": process.status(),
                "username": process.username(),
            }

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
        
    def terminate_process(self, port_number, pid):
        if pid is None:
            return False

        try:
            process = psutil.Process(pid)

            if not process.is_running():
                return False

            connections = process.net_connections(kind="inet")

            owns_port = any(
                connection.status == "LISTEN"
                and connection.laddr.port == port_number
                for connection in connections
            )

            if not owns_port:
                return False

            process.terminate()
            process.wait(timeout=3)

            return True

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.TimeoutExpired
        ):
            return False