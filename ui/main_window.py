from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)

from plugins.port_manager import PortManager


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Ubuntu DevTools - Port Manager")
        self.resize(900, 500)

        self.port_manager = PortManager()

        # Main widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        layout = QVBoxLayout()
        central_widget.setLayout(layout)

        # Title
        title = QLabel("Port Manager")
        layout.addWidget(title)

        # Port table
        self.port_table = QTableWidget()

        self.port_table.setColumnCount(6)

        self.port_table.setHorizontalHeaderLabels([
            "Port",
            "Address",
            "Protocol",
            "PID",
            "Process",
            "Status"
        ])

        self.port_table.setEditTriggers(QTableWidget.NoEditTriggers)

        self.port_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )

        layout.addWidget(self.port_table)

        # Load port data
        self.load_ports()

    def load_ports(self):
        ports = self.port_manager.get_active_ports()

        self.port_table.setRowCount(len(ports))

        for row, port in enumerate(ports):

            self.port_table.setItem(
                row, 0, QTableWidgetItem(str(port["port"]))
            )

            self.port_table.setItem(
                row, 1, QTableWidgetItem(port["address"])
            )

            self.port_table.setItem(
                row, 2, QTableWidgetItem(port["protocol"])
            )

            pid = port["pid"]

            self.port_table.setItem(
                row, 3,
                QTableWidgetItem(
                    str(pid) if pid is not None else "-"
                )
            )

            self.port_table.setItem(
                row, 4, QTableWidgetItem(port["process"])
            )

            self.port_table.setItem(
                row, 5, QTableWidgetItem(port["status"])
            )