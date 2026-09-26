from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QPushButton,
    QLineEdit,
    QMessageBox,
)


from plugins.port_manager import PortManager


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Ubuntu DevTools - Port Manager")
        self.resize(1000, 600)

        self.port_manager = PortManager()

        # =========================
        # Main Widget
        # =========================

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        # =========================
        # Title
        # =========================

        title = QLabel("Ubuntu DevTools")
        title.setStyleSheet("""
            QLabel {
                font-size: 24px;
                font-weight: bold;
            }
        """)

        main_layout.addWidget(title)

        subtitle = QLabel("Port Manager")
        subtitle.setStyleSheet("""
            QLabel {
                font-size: 18px;
            }
        """)

        main_layout.addWidget(subtitle)

        # =========================
        # Search Area
        # =========================

        search_layout = QHBoxLayout()

        search_label = QLabel("Search Port:")

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter port number...")

        search_button = QPushButton("Search")
        search_button.clicked.connect(self.search_port)

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.load_ports)

        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(search_button)
        search_layout.addWidget(refresh_button)

        main_layout.addLayout(search_layout)

        # =========================
        # Port Table
        # =========================

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

        # Make table read-only
        self.port_table.setEditTriggers(
            QTableWidget.NoEditTriggers
        )

        # Select complete row
        self.port_table.setSelectionBehavior(
            QTableWidget.SelectRows
        )

        # Only one row at a time
        self.port_table.setSelectionMode(
            QTableWidget.SingleSelection
        )

        # Stretch columns
        self.port_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )

        # When user selects a row
        self.port_table.itemSelectionChanged.connect(
            self.show_selected_process
        )

        main_layout.addWidget(self.port_table)

        # =========================
        # Selected Process Section
        # =========================

        process_title = QLabel("Selected Process")

        process_title.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
            }
        """)

        main_layout.addWidget(process_title)

        self.process_info = QLabel(
            "No process selected."
        )

        self.process_info.setStyleSheet("""
            QLabel {
                padding: 8px;
            }
        """)

        main_layout.addWidget(self.process_info)

        # =========================
        # Process Buttons
        # =========================

        button_layout = QHBoxLayout()

        button_layout.addStretch()

        details_button = QPushButton(
            "Process Details"
        )

        details_button.clicked.connect(
            self.show_process_details
        )

        kill_button = QPushButton(
            "Kill"
        )

        kill_button.clicked.connect(
            self.kill_selected_process
        )

        button_layout.addWidget(details_button)
        button_layout.addWidget(kill_button)

        main_layout.addLayout(button_layout)

        # =========================
        # Initial Data
        # =========================

        self.load_ports()

    # ==================================================
    # Load Ports
    # ==================================================

    def load_ports(self):

        ports = self.port_manager.get_active_ports()

        self.port_table.setRowCount(len(ports))

        for row, port in enumerate(ports):

            # Port
            self.port_table.setItem(
                row,
                0,
                QTableWidgetItem(
                    str(port["port"])
                )
            )

            # Address
            self.port_table.setItem(
                row,
                1,
                QTableWidgetItem(
                    port["address"]
                )
            )

            # Protocol
            self.port_table.setItem(
                row,
                2,
                QTableWidgetItem(
                    port["protocol"]
                )
            )

            # PID
            pid = port["pid"]

            self.port_table.setItem(
                row,
                3,
                QTableWidgetItem(
                    str(pid)
                    if pid is not None
                    else "-"
                )
            )

            # Process
            self.port_table.setItem(
                row,
                4,
                QTableWidgetItem(
                    port["process"]
                )
            )

            # Status
            self.port_table.setItem(
                row,
                5,
                QTableWidgetItem(
                    port["status"]
                )
            )

        # Clear selected process information
        self.process_info.setText(
            "No process selected."
        )

    # ==================================================
    # Search Port
    # ==================================================

    def search_port(self):

        text = self.search_input.text().strip()

        if not text:
            QMessageBox.information(
                self,
                "Search",
                "Please enter a port number."
            )
            return

        try:
            port_number = int(text)

        except ValueError:
            QMessageBox.warning(
                self,
                "Invalid Port",
                "Please enter a valid port number."
            )
            return

        port = self.port_manager.find_port(
            port_number
        )

        if port is None:

            QMessageBox.information(
                self,
                "Port Not Found",
                f"Port {port_number} is not currently in use."
            )

            return

        # Find matching row in table
        for row in range(
            self.port_table.rowCount()
        ):

            port_item = self.port_table.item(
                row,
                0
            )

            if port_item is None:
                continue

            if int(port_item.text()) == port_number:

                self.port_table.selectRow(row)

                self.port_table.scrollToItem(
                    port_item
                )

                return

    # ==================================================
    # Selected Process
    # ==================================================

    def show_selected_process(self):

        selected_rows = (
            self.port_table.selectionModel()
            .selectedRows()
        )

        if not selected_rows:

            self.process_info.setText(
                "No process selected."
            )

            return

        row = selected_rows[0].row()

        pid_item = self.port_table.item(
            row,
            3
        )

        process_item = self.port_table.item(
            row,
            4
        )

        if pid_item is None:
            return

        pid_text = pid_item.text()

        if pid_text == "-":

            self.process_info.setText(
                "No process information available."
            )

            return

        pid = int(pid_text)

        process_details = (
            self.port_manager
            .get_process_details(pid)
        )

        if process_details is None:

            self.process_info.setText(
                "Process information is unavailable."
            )

            return

        self.process_info.setText(
            f"PID: {process_details['pid']}   |   "
            f"Process: {process_details['name']}   |   "
            f"Status: {process_details['status']}   |   "
            f"User: {process_details['username']}"
        )

    # ==================================================
    # Process Details
    # ==================================================

    def show_process_details(self):

        selected_rows = (
            self.port_table.selectionModel()
            .selectedRows()
        )

        if not selected_rows:

            QMessageBox.information(
                self,
                "Process Details",
                "Please select a process first."
            )

            return

        row = selected_rows[0].row()

        pid_item = self.port_table.item(
            row,
            3
        )

        if pid_item is None:
            return

        pid_text = pid_item.text()

        if pid_text == "-":

            QMessageBox.information(
                self,
                "Process Details",
                "No process is associated with this port."
            )

            return

        pid = int(pid_text)

        details = (
            self.port_manager
            .get_process_details(pid)
        )

        if details is None:

            QMessageBox.warning(
                self,
                "Process Details",
                "Process information is unavailable."
            )

            return

        message = (
            f"PID: {details['pid']}\n"
            f"Name: {details['name']}\n"
            f"Status: {details['status']}\n"
            f"Username: {details['username']}"
        )

        QMessageBox.information(
            self,
            "Process Details",
            message
        )

    # ==================================================
    # Kill Process
    # ==================================================

    def kill_selected_process(self):

        selected_rows = (
            self.port_table.selectionModel()
            .selectedRows()
        )

        if not selected_rows:

            QMessageBox.information(
                self,
                "Kill Process",
                "Please select a process first."
            )

            return

        row = selected_rows[0].row()

        port_item = self.port_table.item(
            row,
            0
        )

        pid_item = self.port_table.item(
            row,
            3
        )

        process_item = self.port_table.item(
            row,
            4
        )

        if (
            port_item is None
            or pid_item is None
            or process_item is None
        ):
            return

        port_number = int(
            port_item.text()
        )

        pid_text = pid_item.text()

        process_name = process_item.text()

        if pid_text == "-":

            QMessageBox.information(
                self,
                "Kill Process",
                "This port has no accessible process PID."
            )

            return

        pid = int(pid_text)

        # Confirmation
        confirmation = QMessageBox.question(
            self,
            "Confirm Process Termination",
            (
                f"Are you sure you want to terminate "
                f"'{process_name}' (PID {pid})?\n\n"
                f"Port: {port_number}"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if confirmation != QMessageBox.Yes:
            return

        # Try to terminate
        success = (
            self.port_manager
            .terminate_process(
                port_number,
                pid
            )
        )

        if success:

            QMessageBox.information(
                self,
                "Process Terminated",
                (
                    f"Process {pid} "
                    f"terminated successfully."
                )
            )

            # Refresh table
            self.load_ports()

        else:

            QMessageBox.warning(
                self,
                "Termination Failed",
                (
                    f"Could not terminate "
                    f"process {pid}."
                )
            )