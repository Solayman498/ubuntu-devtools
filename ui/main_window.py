import sys
from pathlib import Path
from openpyxl import Workbook

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QComboBox,
    QInputDialog,
    QFileDialog,
    QMessageBox,
    QMenu,
)

from plugins.port_manager import PortManager
from core.project_registry import ProjectRegistry
from plugins.workspace_launcher.discovery import ProjectDiscovery


# ==================================================
# Project Scan Worker
# ==================================================

class ProjectScanWorker(QThread):

    scan_completed = Signal(object)
    failed = Signal(str)

    def __init__(self, mode="workspace", root_path=None):
        super().__init__()
        self.mode = mode
        self.root_path = root_path

    def run(self):
        try:
            discovery = ProjectDiscovery()
            projects = discovery.discover(
                root_path=self.root_path,
                mode=self.mode,
            )
            self.scan_completed.emit(projects)
        except Exception as error:
            self.failed.emit(str(error))


# ==================================================
# Main Window
# ==================================================

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Ubuntu DevTools")
        self.resize(1150, 750)

        self.port_manager = PortManager()
        self.project_registry = ProjectRegistry()

        self.scan_worker = None
        self.selected_scan_path = None

        self.setup_ui()
        self.load_dashboard()

    # ==================================================
    # Main UI
    # ==================================================

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        central_widget.setLayout(main_layout)

        sidebar = self.create_sidebar()

        self.pages = QStackedWidget()

        self.dashboard_page = self.create_dashboard_page()
        self.projects_page = self.create_projects_page()
        self.workspace_page = self.create_workspace_page()
        self.port_page = self.create_port_page()

        self.pages.addWidget(self.dashboard_page)
        self.pages.addWidget(self.projects_page)
        self.pages.addWidget(self.workspace_page)
        self.pages.addWidget(self.port_page)

        main_layout.addWidget(sidebar)
        main_layout.addWidget(self.pages)

        self.setStyleSheet(self.get_stylesheet())

    # ==================================================
    # Sidebar
    # ==================================================

    def create_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)

        layout = QVBoxLayout()
        layout.setContentsMargins(18, 24, 18, 18)
        layout.setSpacing(8)

        sidebar.setLayout(layout)

        logo = QLabel("Ubuntu DevTools")
        logo.setObjectName("Logo")

        subtitle = QLabel("Developer Productivity")
        subtitle.setObjectName("SidebarSubtitle")

        layout.addWidget(logo)
        layout.addWidget(subtitle)

        layout.addSpacing(25)

        self.navigation = QListWidget()
        self.navigation.setObjectName("Navigation")

        items = [
            "Dashboard",
            "Projects",
            "Workspace Launcher",
            "Port Manager",
        ]

        for item_text in items:
            item = QListWidgetItem(item_text)
            self.navigation.addItem(item)

        self.navigation.currentRowChanged.connect(self.change_page)
        layout.addWidget(self.navigation)

        layout.addStretch()

        version = QLabel("Ubuntu DevTools\nv0.1.0")
        version.setObjectName("Version")
        layout.addWidget(version)

        self.navigation.setCurrentRow(0)
        return sidebar

    # ==================================================
    # Page Navigation
    # ==================================================

    def change_page(self, index):
        self.pages.setCurrentIndex(index)

        if index == 0:
            self.load_dashboard()
        elif index == 1:
            self.load_projects()
        elif index == 3:
            self.load_ports()

    # ==================================================
    # Dashboard Page
    # ==================================================

    def create_dashboard_page(self):
        page = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(35, 30, 35, 30)
        layout.setSpacing(20)

        page.setLayout(layout)

        title = QLabel("Dashboard")
        title.setObjectName("PageTitle")

        subtitle = QLabel("Your development workspace at a glance.")
        subtitle.setObjectName("PageSubtitle")

        layout.addWidget(title)
        layout.addWidget(subtitle)

        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(15)

        self.project_count_card = self.create_stat_card("Projects", "0")
        self.running_count_card = self.create_stat_card("Running", "0")
        self.port_count_card = self.create_stat_card("Active Ports", "0")

        stats_layout.addWidget(self.project_count_card)
        stats_layout.addWidget(self.running_count_card)
        stats_layout.addWidget(self.port_count_card)

        layout.addLayout(stats_layout)

        section_title = QLabel("Your Projects")
        section_title.setObjectName("SectionTitle")

        layout.addWidget(section_title)

        self.dashboard_projects = QTableWidget()
        self.dashboard_projects.setColumnCount(4)
        self.dashboard_projects.setHorizontalHeaderLabels([
            "Project",
            "Type",
            "Location",
            "Status"
        ])
        self.dashboard_projects.setEditTriggers(QTableWidget.NoEditTriggers)
        self.dashboard_projects.setSelectionBehavior(QTableWidget.SelectRows)
        self.dashboard_projects.setSelectionMode(QTableWidget.SingleSelection)
        self.dashboard_projects.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        layout.addWidget(self.dashboard_projects)

        return page

    # ==================================================
    # Statistic Card Generator
    # ==================================================

    def create_stat_card(self, title, value):
        card = QFrame()
        card.setObjectName("StatCard")

        layout = QVBoxLayout()
        layout.setContentsMargins(18, 15, 18, 15)
        card.setLayout(layout)

        title_label = QLabel(title)
        title_label.setObjectName("StatTitle")

        value_label = QLabel(value)
        value_label.setObjectName("StatValue")

        card.value_label = value_label

        layout.addWidget(title_label)
        layout.addWidget(value_label)

        return card

    # ==================================================
    # Projects Page
    # ==================================================

    def create_projects_page(self):
        page = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(35, 25, 35, 25)
        layout.setSpacing(15)
        page.setLayout(layout)

        # Top Header Section
        header_layout = QHBoxLayout()
        header_text_layout = QVBoxLayout()

        title = QLabel("Projects")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Discover, organize and manage your development projects.")
        subtitle.setObjectName("PageSubtitle")

        header_text_layout.addWidget(title)
        header_text_layout.addWidget(subtitle)

        self.add_project_button = QPushButton("Add Project")
        self.add_project_button.setCursor(Qt.PointingHandCursor)
        self.add_project_button.clicked.connect(self.manually_add_project)

        header_layout.addLayout(header_text_layout)
        header_layout.addStretch()
        header_layout.addWidget(self.add_project_button)

        layout.addLayout(header_layout)

        # Summary Stats Cards
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(12)

        self.card_total = self.create_stat_card("TOTAL PROJECTS", "0")
        self.card_detected = self.create_stat_card("DETECTED", "0")
        self.card_running = self.create_stat_card("RUNNING", "0")

        stats_layout.addWidget(self.card_total)
        stats_layout.addWidget(self.card_detected)
        stats_layout.addWidget(self.card_running)

        layout.addLayout(stats_layout)

        # Search Bar Section
        search_filter_layout = QHBoxLayout()

        self.project_search_bar = QLineEdit()
        self.project_search_bar.setPlaceholderText("Search projects...")
        self.project_search_bar.textChanged.connect(self.filter_projects_table)

        search_filter_layout.addWidget(self.project_search_bar)

        layout.addLayout(search_filter_layout)

        # Filter Tabs & Options
        tabs_layout = QHBoxLayout()

        self.btn_tab_all = QPushButton("All Projects")
        self.btn_tab_all.setObjectName("TabButtonActive")
        self.btn_tab_all.clicked.connect(lambda: self.switch_project_tab("all"))

        self.btn_tab_running = QPushButton("Running")
        self.btn_tab_running.setObjectName("TabButton")
        self.btn_tab_running.clicked.connect(lambda: self.switch_project_tab("running"))

        self.btn_tab_scanned = QPushButton("Recently Scanned")
        self.btn_tab_scanned.setObjectName("TabButton")
        self.btn_tab_scanned.clicked.connect(lambda: self.switch_project_tab("scanned"))

        self.more_menu_button = QPushButton("More")
        self.more_menu_button.setObjectName("TabButton")
        self.more_menu_button.setCursor(Qt.PointingHandCursor)

        more_menu = QMenu(self)
        action_export = more_menu.addAction("Export to Excel")
        action_export.triggered.connect(self.export_projects_to_excel)

        action_restore = more_menu.addAction("Manage Ignored Projects")
        action_restore.triggered.connect(self.restore_ignored_project)

        self.more_menu_button.setMenu(more_menu)

        tabs_layout.addWidget(self.btn_tab_all)
        tabs_layout.addWidget(self.btn_tab_running)
        tabs_layout.addWidget(self.btn_tab_scanned)
        tabs_layout.addStretch()
        tabs_layout.addWidget(self.more_menu_button)

        layout.addLayout(tabs_layout)

        # Main Projects Table
        self.projects_table = QTableWidget()
        self.projects_table.setColumnCount(5)
        self.projects_table.setHorizontalHeaderLabels([
            "Name",
            "Type",
            "Location",
            "Status",
            "Actions"
        ])
        self.projects_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.projects_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.projects_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.projects_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)

        layout.addWidget(self.projects_table)

        # Bottom Scan Control Deck
        scan_card = QFrame()
        scan_card.setObjectName("ScanCard")

        scan_card_layout = QVBoxLayout()
        scan_card_layout.setContentsMargins(15, 12, 15, 12)
        scan_card_layout.setSpacing(8)
        scan_card.setLayout(scan_card_layout)

        self.scan_location_label = QLabel(f"Scan Location: {Path.home()}")
        self.scan_location_label.setObjectName("ScanLocationText")

        controls_row = QHBoxLayout()

        self.scan_mode_combo = QComboBox()
        self.scan_mode_combo.addItem("Developer Workspace Scan", "workspace")
        self.scan_mode_combo.addItem("Full System Scan", "full")

        self.browse_scan_button = QPushButton("Browse")
        self.browse_scan_button.clicked.connect(self.browse_scan_location)

        self.scan_button = QPushButton("Scan Projects")
        self.scan_button.clicked.connect(self.scan_projects)

        controls_row.addWidget(self.scan_mode_combo, stretch=2)
        controls_row.addWidget(self.browse_scan_button, stretch=1)
        controls_row.addWidget(self.scan_button, stretch=2)

        scan_card_layout.addWidget(self.scan_location_label)
        scan_card_layout.addLayout(controls_row)

        layout.addWidget(scan_card)

        # Footer Status Bar
        footer_layout = QHBoxLayout()
        self.scan_status = QLabel("Ready to scan.")
        self.scan_status.setObjectName("PageSubtitle")

        self.last_scan_label = QLabel("Last scan: Today")
        self.last_scan_label.setObjectName("PageSubtitle")

        footer_layout.addWidget(self.scan_status)
        footer_layout.addStretch()
        footer_layout.addWidget(self.last_scan_label)

        layout.addLayout(footer_layout)

        self.current_tab_filter = "all"
        return page

    # ==================================================
    # Workspace Launcher Page (FULL RESTORED)
    # ==================================================

    def create_workspace_page(self):
        page = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(35, 30, 35, 30)
        layout.setSpacing(18)
        page.setLayout(layout)

        title = QLabel("Workspace Launcher")
        title.setObjectName("PageTitle")

        subtitle = QLabel("Analyze, prepare and launch your projects.")
        subtitle.setObjectName("PageSubtitle")

        layout.addWidget(title)
        layout.addWidget(subtitle)

        info_card = QFrame()
        info_card.setObjectName("InfoCard")

        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(20, 18, 20, 18)
        info_card.setLayout(info_layout)

        info_title = QLabel("Workspace Automation")
        info_title.setObjectName("SectionTitle")

        info_text = QLabel(
            "Select a project from the registry to analyze its environment, "
            "inspect marker files, prepare execution scripts, and launch development servers."
        )
        info_text.setWordWrap(True)

        info_layout.addWidget(info_title)
        info_layout.addWidget(info_text)

        layout.addWidget(info_card)
        layout.addStretch()

        return page

    # ==================================================
    # Port Manager Page (FULL RESTORED)
    # ==================================================

    def create_port_page(self):
        page = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(35, 30, 35, 30)
        layout.setSpacing(15)
        page.setLayout(layout)

        title = QLabel("Port Manager")
        title.setObjectName("PageTitle")

        subtitle = QLabel("Monitor and manage active network ports.")
        subtitle.setObjectName("PageSubtitle")

        layout.addWidget(title)
        layout.addWidget(subtitle)

        # Search Row
        search_layout = QHBoxLayout()

        self.port_search_field = QLineEdit()
        self.port_search_field.setPlaceholderText("Enter port number...")

        search_button = QPushButton("Search")
        search_button.clicked.connect(self.search_port)

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.load_ports)

        search_layout.addWidget(self.port_search_field)
        search_layout.addWidget(search_button)
        search_layout.addWidget(refresh_button)

        layout.addLayout(search_layout)

        # Ports Table
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
        self.port_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.port_table.setSelectionMode(QTableWidget.SingleSelection)
        self.port_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.port_table.itemSelectionChanged.connect(self.show_selected_process)

        layout.addWidget(self.port_table)

        # Process Details Banner
        self.process_info = QLabel("No process selected.")
        self.process_info.setObjectName("ProcessInfo")
        layout.addWidget(self.process_info)

        # Action Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        details_button = QPushButton("Process Details")
        details_button.clicked.connect(self.show_process_details)

        kill_button = QPushButton("Kill")
        kill_button.clicked.connect(self.kill_selected_process)

        button_layout.addWidget(details_button)
        button_layout.addWidget(kill_button)

        layout.addLayout(button_layout)

        return page

    # ==================================================
    # Port Manager Methods
    # ==================================================

    def load_ports(self):
        ports = self.port_manager.get_active_ports()
        self.port_table.setRowCount(len(ports))

        for row, port in enumerate(ports):
            values = [
                str(port["port"]),
                port["address"],
                port["protocol"],
                str(port["pid"]) if port["pid"] is not None else "-",
                port["process"],
                port["status"]
            ]

            for column, value in enumerate(values):
                self.port_table.setItem(row, column, QTableWidgetItem(value))

        self.process_info.setText("No process selected.")

    def search_port(self):
        text = self.port_search_field.text().strip()
        if not text:
            return

        try:
            port_number = int(text)
        except ValueError:
            return

        port = self.port_manager.find_port(port_number)
        if port is None:
            return

        for row in range(self.port_table.rowCount()):
            item = self.port_table.item(row, 0)
            if item and int(item.text()) == port_number:
                self.port_table.selectRow(row)
                self.port_table.scrollToItem(item)
                return

    def show_selected_process(self):
        selected_rows = self.port_table.selectionModel().selectedRows()
        if not selected_rows:
            self.process_info.setText("No process selected.")
            return

        row = selected_rows[0].row()
        pid_item = self.port_table.item(row, 3)

        if not pid_item or pid_item.text() == "-":
            self.process_info.setText("No process information available.")
            return

        pid = int(pid_item.text())
        details = self.port_manager.get_process_details(pid)

        if details is None:
            return

        self.process_info.setText(
            f"PID: {details['pid']}   |   "
            f"Process: {details['name']}   |   "
            f"Status: {details['status']}   |   "
            f"User: {details['username']}"
        )

    def show_process_details(self):
        selected_rows = self.port_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        pid_item = self.port_table.item(row, 3)

        if not pid_item or pid_item.text() == "-":
            return

        pid = int(pid_item.text())
        details = self.port_manager.get_process_details(pid)

        if not details:
            return

        message = (
            f"PID: {details['pid']}\n"
            f"Name: {details['name']}\n"
            f"Status: {details['status']}\n"
            f"Username: {details['username']}"
        )
        QMessageBox.information(self, "Process Details", message)

    def kill_selected_process(self):
        selected_rows = self.port_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        port_item = self.port_table.item(row, 0)
        pid_item = self.port_table.item(row, 3)
        process_item = self.port_table.item(row, 4)

        if not port_item or not pid_item or not process_item or pid_item.text() == "-":
            return

        port_number = int(port_item.text())
        pid = int(pid_item.text())
        process_name = process_item.text()

        confirmation = QMessageBox.question(
            self,
            "Confirm Process Termination",
            f"Terminate '{process_name}' (PID {pid})?\n\nPort: {port_number}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if confirmation != QMessageBox.Yes:
            return

        success = self.port_manager.terminate_process(port_number, pid)

        if success:
            self.load_ports()
            self.load_dashboard()
        else:
            QMessageBox.warning(self, "Termination Failed", f"Could not terminate process {pid}.")

    # ==================================================
    # Tab Switching Logic
    # ==================================================

    def switch_project_tab(self, tab_type):
        self.current_tab_filter = tab_type

        self.btn_tab_all.setObjectName("TabButtonActive" if tab_type == "all" else "TabButton")
        self.btn_tab_running.setObjectName("TabButtonActive" if tab_type == "running" else "TabButton")
        self.btn_tab_scanned.setObjectName("TabButtonActive" if tab_type == "scanned" else "TabButton")

        self.setStyleSheet(self.get_stylesheet())
        self.filter_projects_table()

    # ==================================================
    # Table Filtering
    # ==================================================

    def filter_projects_table(self):
        search_query = self.project_search_bar.text().lower().strip()

        for row in range(self.projects_table.rowCount()):
            name_item = self.projects_table.item(row, 0)
            type_item = self.projects_table.item(row, 1)
            status_item = self.projects_table.item(row, 3)

            if not name_item or not type_item or not status_item:
                continue

            name_text = name_item.text().lower()
            type_text = type_item.text().lower()
            status_text = status_item.text().lower()

            matches_search = search_query in name_text or search_query in type_text

            matches_tab = True
            if self.current_tab_filter == "running":
                matches_tab = "running" in status_text

            show_row = matches_search and matches_tab
            self.projects_table.setRowHidden(row, not show_row)

    # ==================================================
    # Projects Data Loading
    # ==================================================

    def load_projects(self):
        projects = self.project_registry.get_projects()
        self.projects_table.setRowCount(len(projects))

        detected_count = 0
        running_count = 0

        for row, project in enumerate(projects):
            name = project.get("name", "Unnamed")
            p_type = project.get("project_type", "Unknown")
            path = project.get("path", "")
            confidence = str(project.get("confidence", "Medium"))
            status = project.get("status", "Idle")

            if confidence != "Manual":
                detected_count += 1
            if status == "Running":
                running_count += 1

            name_item = QTableWidgetItem(f"{name}\n   {confidence} confidence")
            name_item.setData(Qt.ItemDataRole.UserRole, project.get("id"))

            type_item = QTableWidgetItem(p_type)

            path_item = QTableWidgetItem(path)
            path_item.setToolTip(path)

            status_item = QTableWidgetItem(status)

            self.projects_table.setItem(row, 0, name_item)
            self.projects_table.setItem(row, 1, type_item)
            self.projects_table.setItem(row, 2, path_item)
            self.projects_table.setItem(row, 3, status_item)

            action_btn = QPushButton("...")
            action_btn.setObjectName("RowActionMenu")
            action_btn.setFixedWidth(30)
            action_btn.setCursor(Qt.PointingHandCursor)

            menu = QMenu(self)
            menu.addAction("Detection Details", lambda r=row: self.show_project_detection_details_by_row(r))
            menu.addAction("View Full Path", lambda r=row: self.show_selected_project_path_by_row(r))
            menu.addAction("Ignore Project", lambda r=row: self.ignore_selected_project_by_row(r))
            menu.addAction("Delete Project", lambda r=row: self.delete_selected_project_by_row(r))

            action_btn.setMenu(menu)
            self.projects_table.setCellWidget(row, 4, action_btn)

        self.card_total.value_label.setText(str(len(projects)))
        self.card_detected.value_label.setText(str(detected_count))
        self.card_running.value_label.setText(str(running_count))

        self.filter_projects_table()

    # ==================================================
    # Row Actions Helpers
    # ==================================================

    def show_project_detection_details_by_row(self, row):
        self.projects_table.selectRow(row)
        self.show_project_detection_details()

    def show_selected_project_path_by_row(self, row):
        self.projects_table.selectRow(row)
        self.show_selected_project_path()

    def ignore_selected_project_by_row(self, row):
        self.projects_table.selectRow(row)
        self.ignore_selected_project()

    def delete_selected_project_by_row(self, row):
        self.projects_table.selectRow(row)
        self.delete_selected_project()

    # ==================================================
    # Scan Handlers
    # ==================================================

    def browse_scan_location(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Folder to Scan",
            str(Path.home()),
        )
        if folder:
            self.selected_scan_path = str(Path(folder).resolve())
            self.scan_location_label.setText(f"Scan Location: {self.selected_scan_path}")

    def scan_projects(self):
        mode = self.scan_mode_combo.currentData()
        root_path = self.selected_scan_path if self.selected_scan_path else ("/" if mode == "full" else str(Path.home()))

        self.current_scan_mode = mode
        self.current_scan_root = str(Path(root_path).resolve())

        self.scan_button.setEnabled(False)
        self.browse_scan_button.setEnabled(False)
        self.scan_status.setText(f"Scanning {self.current_scan_root}...")

        self.scan_worker = ProjectScanWorker(mode=mode, root_path=root_path)
        self.scan_worker.scan_completed.connect(self.scan_finished)
        self.scan_worker.failed.connect(self.scan_failed)
        self.scan_worker.finished.connect(self.cleanup_scan_worker)
        self.scan_worker.start()

    def scan_finished(self, projects):
        root = self.current_scan_root
        mode = self.current_scan_mode

        if mode == "full" and root == "/":
            if projects:
                self.project_registry.replace_projects(projects)
            else:
                self.scan_status.setText("No projects found. Existing registry preserved.")
                self.load_projects()
                return
        else:
            self.project_registry.sync_projects_in_path(projects, root)

        self.load_projects()
        if hasattr(self, "load_dashboard"):
            self.load_dashboard()

        self.scan_status.setText(f"Scan completed. {len(projects)} projects found.")

    def scan_failed(self, error_message):
        self.scan_status.setText(f"Scan failed: {error_message}")
        QMessageBox.warning(self, "Project Scan Failed", error_message)

    def cleanup_scan_worker(self):
        self.scan_button.setEnabled(True)
        self.browse_scan_button.setEnabled(True)
        if hasattr(self, "scan_worker") and self.scan_worker is not None:
            self.scan_worker.deleteLater()
            self.scan_worker = None

    # ==================================================
    # Operations Logic
    # ==================================================

    def show_project_detection_details(self):
        row = self.projects_table.currentRow()
        if row < 0:
            return

        name_item = self.projects_table.item(row, 0)
        type_item = self.projects_table.item(row, 1)
        path_item = self.projects_table.item(row, 2)
        status_item = self.projects_table.item(row, 3)

        if not name_item or not path_item:
            return

        raw_name = name_item.text().split("\n")[0].strip()
        path = path_item.text()
        project_type = type_item.text() if type_item else "Unknown"
        status = status_item.text() if status_item else "Unknown"

        project_path = Path(path)
        lines = [
            f"Name: {raw_name}",
            f"Project Type: {project_type}",
            f"Status: {status}",
            f"Root Directory: {path}",
            "",
        ]

        if not project_path.is_dir():
            lines.append("Detection Result: Directory missing.")
        else:
            try:
                discovery = ProjectDiscovery()
                result = discovery.detector.detect(str(project_path))
                if not result or result.get("type") == "Unknown":
                    lines.append("Current Detection Result: Not recognized")
                else:
                    lines.extend([
                        f"Current Detected Type: {result.get('type', 'Unknown')}",
                        "Detected Marker Files:",
                    ])
                    for file_name in result.get("files", []):
                        lines.append(f"  - {file_name}")
            except Exception as error:
                lines.append(f"Could not inspect project: {error}")

        dialog = QMessageBox(self)
        dialog.setWindowTitle("Project Detection Details")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText(f"Detection Details - {raw_name}")
        dialog.setInformativeText("\n".join(lines))
        dialog.exec()

    def manually_add_project(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Project Folder", str(Path.home()))
        if not folder:
            return

        project_path = Path(folder).resolve()
        path_string = str(project_path)

        try:
            discovery = ProjectDiscovery()
            result = discovery.detector.detect(path_string)
            detected_type = result.get("type", "Manual") if result else "Manual"
        except Exception:
            detected_type = "Manual"

        project = {
            "name": project_path.name or path_string,
            "path": path_string,
            "type": detected_type,
            "confidence": "Manual",
            "files": [],
        }

        self.project_registry.register_project(project)
        self.load_projects()
        self.load_dashboard()

    def show_selected_project_path(self):
        row = self.projects_table.currentRow()
        if row >= 0 and self.projects_table.item(row, 2):
            full_path = self.projects_table.item(row, 2).text()
            QMessageBox.information(self, "Full Path", full_path)

    def ignore_selected_project(self):
        row = self.projects_table.currentRow()
        if row >= 0 and self.projects_table.item(row, 0) and self.projects_table.item(row, 2):
            raw_name = self.projects_table.item(row, 0).text().split("\n")[0].strip()
            path = self.projects_table.item(row, 2).text()
            self.project_registry.ignore_project(path, raw_name)
            self.load_projects()

    def restore_ignored_project(self):
        ignored = self.project_registry.get_ignored_projects()
        if not ignored:
            QMessageBox.information(self, "Ignored Projects", "No ignored projects found.")
            return
        names = [f"{p['name']} - {p['path']}" for p in ignored]
        selected, ok = QInputDialog.getItem(self, "Restore Project", "Select to restore:", names, 0, False)
        if ok and selected:
            idx = names.index(selected)
            self.project_registry.restore_ignored_project(ignored[idx]["path"])
            self.load_projects()

    def delete_selected_project(self):
        row = self.projects_table.currentRow()
        if row >= 0 and self.projects_table.item(row, 0):
            project_id = self.projects_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if project_id is not None:
                self.project_registry.remove_project(int(project_id))
                self.load_projects()
                self.load_dashboard()

    def export_projects_to_excel(self):
        projects = self.project_registry.get_projects()
        if not projects:
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Export Projects", "projects.xlsx", "Excel Files (*.xlsx)")
        if file_path:
            wb = Workbook()
            ws = wb.active
            ws.append(["Name", "Type", "Path", "Confidence", "Status"])
            for p in projects:
                ws.append([p.get("name"), p.get("project_type"), p.get("path"), str(p.get("confidence")), p.get("status")])
            wb.save(file_path)

    # ==================================================
    # Dashboard Loading
    # ==================================================

    def load_dashboard(self):
        projects = self.project_registry.get_projects()
        self.project_count_card.value_label.setText(str(len(projects)))

        running = sum(1 for p in projects if p.get("status") == "Running")
        self.running_count_card.value_label.setText(str(running))

        ports = self.port_manager.get_active_ports()
        self.port_count_card.value_label.setText(str(len(ports)))

        self.dashboard_projects.setRowCount(len(projects))
        for row, project in enumerate(projects):
            values = [project["name"], project["project_type"], project["path"], project["status"]]
            for column, value in enumerate(values):
                self.dashboard_projects.setItem(row, column, QTableWidgetItem(str(value or "")))

    # ==================================================
    # Stylesheet
    # ==================================================

    def get_stylesheet(self):
        return """
        QMainWindow {
            background-color: #1e1e24;
            color: #e0e0e0;
        }

        QWidget {
            color: #e0e0e0;
            font-family: 'Segoe UI', Ubuntu, sans-serif;
        }

        #Sidebar {
            background-color: #16161a;
            border-right: 1px solid #2b2c34;
        }

        #Logo {
            color: #ffffff;
            font-size: 20px;
            font-weight: bold;
        }

        #SidebarSubtitle, #PageSubtitle {
            color: #72757e;
            font-size: 12px;
        }

        #Navigation {
            background: transparent;
            border: none;
            color: #94a1b2;
            font-size: 14px;
            outline: none;
        }

        #Navigation::item {
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 4px;
        }

        #Navigation::item:selected {
            background-color: #2cb67d;
            color: #ffffff;
            font-weight: bold;
        }

        #PageTitle {
            font-size: 24px;
            font-weight: bold;
            color: #fffffe;
        }

        #StatCard, #ScanCard, #InfoCard {
            background-color: #242629;
            border: 1px solid #2b2c34;
            border-radius: 10px;
        }

        #StatTitle, #SectionTitle {
            color: #fffffe;
            font-size: 16px;
            font-weight: bold;
        }

        #StatTitle {
            color: #72757e;
            font-size: 11px;
        }

        #StatValue {
            color: #fffffe;
            font-size: 22px;
            font-weight: bold;
        }

        #TabButton {
            background-color: transparent;
            color: #94a1b2;
            border: none;
            padding: 6px 14px;
            font-weight: 600;
        }

        #TabButtonActive {
            background-color: #2cb67d;
            color: #ffffff;
            border: none;
            border-radius: 6px;
            padding: 6px 14px;
            font-weight: bold;
        }

        #RowActionMenu {
            background-color: transparent;
            color: #94a1b2;
            font-weight: bold;
            border: none;
        }

        #RowActionMenu:hover {
            color: #fffffe;
            background-color: #383a40;
            border-radius: 4px;
        }

        QLineEdit, QComboBox {
            background-color: #242629;
            border: 1px solid #383a40;
            border-radius: 7px;
            padding: 8px 12px;
            color: #fffffe;
        }

        QPushButton {
            background-color: #2cb67d;
            color: #ffffff;
            border: none;
            border-radius: 7px;
            padding: 8px 16px;
            font-weight: 600;
        }

        QPushButton:hover {
            background-color: #259d6c;
        }

        #ProcessInfo {
            background-color: #242629;
            border: 1px solid #2b2c34;
            border-radius: 7px;
            padding: 12px;
            color: #94a1b2;
        }

        QTableWidget {
            background-color: #242629;
            border: 1px solid #2b2c34;
            border-radius: 8px;
            gridline-color: #2b2c34;
            color: #fffffe;
        }

        QHeaderView::section {
            background-color: #16161a;
            color: #94a1b2;
            padding: 10px;
            border: none;
            border-bottom: 1px solid #2b2c34;
            font-weight: bold;
        }
        """


# ==================================================
# Run Application
# ==================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())