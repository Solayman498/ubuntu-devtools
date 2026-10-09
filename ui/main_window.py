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
        self.resize(1150, 700)

        self.port_manager = PortManager()
        self.project_registry = ProjectRegistry()

        self.scan_worker = None

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

        self.setStyleSheet(
            self.get_stylesheet()
        )

    # ==================================================
    # Sidebar
    # ==================================================

    def create_sidebar(self):

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)

        layout = QVBoxLayout()

        layout.setContentsMargins(
            18,
            24,
            18,
            18
        )

        layout.setSpacing(8)

        sidebar.setLayout(layout)

        logo = QLabel(
            "Ubuntu DevTools"
        )

        logo.setObjectName("Logo")

        subtitle = QLabel(
            "Developer Productivity"
        )

        subtitle.setObjectName(
            "SidebarSubtitle"
        )

        layout.addWidget(logo)
        layout.addWidget(subtitle)

        layout.addSpacing(25)

        self.navigation = QListWidget()

        self.navigation.setObjectName(
            "Navigation"
        )

        items = [
            "Dashboard",
            "Projects",
            "Workspace Launcher",
            "Port Manager",
        ]

        for item_text in items:

            item = QListWidgetItem(
                item_text
            )

            self.navigation.addItem(
                item
            )

        self.navigation.currentRowChanged.connect(
            self.change_page
        )

        layout.addWidget(
            self.navigation
        )

        layout.addStretch()

        version = QLabel(
            "Ubuntu DevTools\nv0.1.0"
        )

        version.setObjectName(
            "Version"
        )

        layout.addWidget(
            version
        )

        self.navigation.setCurrentRow(0)

        return sidebar

    # ==================================================
    # Page Navigation
    # ==================================================

    def change_page(self, index):

        self.pages.setCurrentIndex(
            index
        )

        if index == 0:

            self.load_dashboard()

        elif index == 1:

            self.load_projects()

        elif index == 3:

            self.load_ports()

    # ==================================================
    # Dashboard
    # ==================================================

    def create_dashboard_page(self):

        page = QWidget()

        layout = QVBoxLayout()

        layout.setContentsMargins(
            35,
            30,
            35,
            30
        )

        layout.setSpacing(20)

        page.setLayout(layout)

        title = QLabel(
            "Dashboard"
        )

        title.setObjectName(
            "PageTitle"
        )

        subtitle = QLabel(
            "Your development workspace at a glance."
        )

        subtitle.setObjectName(
            "PageSubtitle"
        )

        layout.addWidget(title)
        layout.addWidget(subtitle)

        stats_layout = QHBoxLayout()

        stats_layout.setSpacing(15)

        self.project_count_card = (
            self.create_stat_card(
                "Projects",
                "0"
            )
        )

        self.running_count_card = (
            self.create_stat_card(
                "Running",
                "0"
            )
        )

        self.port_count_card = (
            self.create_stat_card(
                "Active Ports",
                "0"
            )
        )

        stats_layout.addWidget(
            self.project_count_card
        )

        stats_layout.addWidget(
            self.running_count_card
        )

        stats_layout.addWidget(
            self.port_count_card
        )

        layout.addLayout(
            stats_layout
        )

        section_title = QLabel(
            "Your Projects"
        )

        section_title.setObjectName(
            "SectionTitle"
        )

        layout.addWidget(
            section_title
        )

        self.dashboard_projects = QTableWidget()

        self.dashboard_projects.setColumnCount(4)

        self.dashboard_projects.setHorizontalHeaderLabels([
            "Project",
            "Type",
            "Location",
            "Status"
        ])

        self.dashboard_projects.setEditTriggers(
            QTableWidget.NoEditTriggers
        )

        self.dashboard_projects.setSelectionBehavior(
            QTableWidget.SelectRows
        )

        self.dashboard_projects.setSelectionMode(
            QTableWidget.SingleSelection
        )

        self.dashboard_projects.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )

        layout.addWidget(
            self.dashboard_projects
        )

        return page

    # ==================================================
    # Statistic Card
    # ==================================================

    def create_stat_card(
        self,
        title,
        value
    ):

        card = QFrame()

        card.setObjectName(
            "StatCard"
        )

        layout = QVBoxLayout()

        layout.setContentsMargins(
            18,
            15,
            18,
            15
        )

        card.setLayout(
            layout
        )

        title_label = QLabel(
            title
        )

        title_label.setObjectName(
            "StatTitle"
        )

        value_label = QLabel(
            value
        )

        value_label.setObjectName(
            "StatValue"
        )

        card.value_label = value_label

        layout.addWidget(
            title_label
        )

        layout.addWidget(
            value_label
        )

        return card

    # ==================================================
    # Projects Page
    # ==================================================

    def create_projects_page(self):

        page = QWidget()

        layout = QVBoxLayout()

        layout.setContentsMargins(
            35,
            30,
            35,
            30
        )

        layout.setSpacing(18)

        page.setLayout(
            layout
        )

        title = QLabel(
            "Projects"
        )

        title.setObjectName(
            "PageTitle"
        )

        subtitle = QLabel(
            "Projects discovered on your system."
        )

        subtitle.setObjectName(
            "PageSubtitle"
        )

        layout.addWidget(
            title
        )

        layout.addWidget(
            subtitle
        )

        self.projects_table = QTableWidget()

        self.projects_table.setColumnCount(6)

        self.projects_table.setHorizontalHeaderLabels([
            "Name",
            "Type",
            "Path",
            "Confidence",
            "Status",
            "Last Scanned"
        ])

        self.projects_table.setEditTriggers(
            QTableWidget.NoEditTriggers
        )

        self.projects_table.setSelectionBehavior(
            QTableWidget.SelectRows
        )

        self.projects_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )

        layout.addWidget(
            self.projects_table
        )

        # Scan mode selector
        self.scan_mode_combo = QComboBox()

        self.scan_mode_combo.addItem(
            "Developer Workspace Scan",
            "workspace",
        )

        self.scan_mode_combo.addItem(
            "Full System Scan",
            "full",
        )

        self.selected_scan_path = None

        self.scan_location_label = QLabel(
            "Default location: Home directory"
        )

        # Browse button
        self.browse_scan_button = QPushButton("Browse Folder")

        self.browse_scan_button.clicked.connect(
            self.browse_scan_location
        )

        # Buttons
        self.scan_button = QPushButton("Scan for Projects")

        self.scan_button.clicked.connect(
            self.scan_projects
        )

        self.export_button = QPushButton("Export to Excel")

        self.export_button.clicked.connect(
            self.export_projects_to_excel
        )

        refresh_button = QPushButton("Refresh")

        refresh_button.clicked.connect(
            self.load_projects
        )

        self.delete_project_button = QPushButton("Delete Project")

        self.delete_project_button.clicked.connect(
            self.delete_selected_project
        )

        self.full_path_button = QPushButton("View Full Path")

        self.full_path_button.clicked.connect(
            self.show_selected_project_path
        )

        self.ignore_button = QPushButton("Ignore Project")

        self.ignore_button.clicked.connect(
            self.ignore_selected_project
        )

        self.restore_button = QPushButton("Manage Ignored")

        self.restore_button.clicked.connect(
            self.restore_ignored_project
        )

        # Layout Setup
        layout.addWidget(self.scan_mode_combo)

        browse_layout = QHBoxLayout()

        browse_layout.addWidget(self.browse_scan_button)

        browse_layout.addWidget(self.scan_location_label)

        browse_layout.addStretch()

        layout.addLayout(browse_layout)

        button_layout = QHBoxLayout()

        button_layout.addWidget(self.scan_button)

        button_layout.addWidget(self.export_button)

        button_layout.addWidget(refresh_button)

        button_layout.addWidget(self.full_path_button)

        button_layout.addWidget(self.delete_project_button)

        button_layout.addWidget(self.ignore_button)

        button_layout.addWidget(self.restore_button)

        button_layout.addStretch()

        layout.addLayout(button_layout)

        self.scan_status = QLabel(
            ""
        )

        self.scan_status.setObjectName(
            "PageSubtitle"
        )

        layout.addWidget(
            self.scan_status
        )

        return page

    # ==================================================
    # Workspace Launcher
    # ==================================================

    def create_workspace_page(self):

        page = QWidget()

        layout = QVBoxLayout()

        layout.setContentsMargins(
            35,
            30,
            35,
            30
        )

        layout.setSpacing(18)

        page.setLayout(
            layout
        )

        title = QLabel(
            "Workspace Launcher"
        )

        title.setObjectName(
            "PageTitle"
        )

        subtitle = QLabel(
            "Analyze, prepare and launch your projects."
        )

        subtitle.setObjectName(
            "PageSubtitle"
        )

        layout.addWidget(
            title
        )

        layout.addWidget(
            subtitle
        )

        info_card = QFrame()

        info_card.setObjectName(
            "InfoCard"
        )

        info_layout = QVBoxLayout()

        info_layout.setContentsMargins(
            20,
            18,
            20,
            18
        )

        info_card.setLayout(
            info_layout
        )

        info_title = QLabel(
            "Workspace Automation"
        )

        info_title.setObjectName(
            "SectionTitle"
        )

        info_text = QLabel(
            "Select a project to analyze its environment, "
            "dependencies and launch it."
        )

        info_text.setWordWrap(
            True
        )

        info_layout.addWidget(
            info_title
        )

        info_layout.addWidget(
            info_text
        )

        layout.addWidget(
            info_card
        )

        layout.addStretch()

        return page

    # ==================================================
    # Port Manager
    # ==================================================

    def create_port_page(self):

        page = QWidget()

        layout = QVBoxLayout()

        layout.setContentsMargins(
            35,
            30,
            35,
            30
        )

        layout.setSpacing(15)

        page.setLayout(
            layout
        )

        title = QLabel(
            "Port Manager"
        )

        title.setObjectName(
            "PageTitle"
        )

        subtitle = QLabel(
            "Monitor and manage active network ports."
        )

        subtitle.setObjectName(
            "PageSubtitle"
        )

        layout.addWidget(
            title
        )

        layout.addWidget(
            subtitle
        )

        # Search

        search_layout = QHBoxLayout()

        self.port_search_field = QLineEdit()

        self.port_search_field.setPlaceholderText(
            "Enter port number..."
        )

        search_button = QPushButton(
            "Search"
        )

        search_button.clicked.connect(
            self.search_port
        )

        refresh_button = QPushButton(
            "Refresh"
        )

        refresh_button.clicked.connect(
            self.load_ports
        )

        search_layout.addWidget(
            self.port_search_field
        )

        search_layout.addWidget(
            search_button
        )

        search_layout.addWidget(
            refresh_button
        )

        layout.addLayout(
            search_layout
        )

        # Table

        self.port_table = QTableWidget()

        self.port_table.setColumnCount(
            6
        )

        self.port_table.setHorizontalHeaderLabels([
            "Port",
            "Address",
            "Protocol",
            "PID",
            "Process",
            "Status"
        ])

        self.port_table.setEditTriggers(
            QTableWidget.NoEditTriggers
        )

        self.port_table.setSelectionBehavior(
            QTableWidget.SelectRows
        )

        self.port_table.setSelectionMode(
            QTableWidget.SingleSelection
        )

        self.port_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )

        self.port_table.itemSelectionChanged.connect(
            self.show_selected_process
        )

        layout.addWidget(
            self.port_table
        )

        self.process_info = QLabel(
            "No process selected."
        )

        self.process_info.setObjectName(
            "ProcessInfo"
        )

        layout.addWidget(
            self.process_info
        )

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

        button_layout.addWidget(
            details_button
        )

        button_layout.addWidget(
            kill_button
        )

        layout.addLayout(
            button_layout
        )

        return page

    # ==================================================
    # Browse Scan Location
    # ==================================================

    def browse_scan_location(self):

        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Folder to Scan",
            str(Path.home()),
        )

        if folder:

            self.selected_scan_path = str(Path(folder).resolve())

            self.scan_location_label.setText(
                f"Selected: {self.selected_scan_path}"
            )

    # ==================================================
    # Scan Projects
    # ==================================================

    def scan_projects(self):

        mode = self.scan_mode_combo.currentData()

        if self.selected_scan_path:

            root_path = self.selected_scan_path

        elif mode == "full":

            root_path = "/"

        else:

            root_path = str(Path.home())

        self.current_scan_mode = mode

        self.current_scan_root = str(Path(root_path).resolve())

        self.scan_button.setEnabled(False)

        self.browse_scan_button.setEnabled(False)

        self.scan_status.setText(
            f"Scanning {self.current_scan_root}..."
        )

        self.scan_worker = ProjectScanWorker(
            mode=mode,
            root_path=root_path,
        )

        self.scan_worker.scan_completed.connect(
            self.scan_finished
        )

        self.scan_worker.failed.connect(
            self.scan_failed
        )

        self.scan_worker.finished.connect(
            self.cleanup_scan_worker
        )

        self.scan_worker.start()

    # ==================================================
    # Scan Finished
    # ==================================================

    def scan_finished(self, projects):

        root = self.current_scan_root

        mode = self.current_scan_mode

        # Full scan of "/" updates the entire registry.
        if mode == "full" and root == "/":

            if projects:

                self.project_registry.replace_projects(projects)

            else:

                self.scan_status.setText(
                    "No projects found. Existing registry was preserved."
                )

                self.load_projects()

                return

        else:

            # A workspace or custom-folder scan must not
            # remove projects registered outside that folder.
            self.project_registry.sync_projects_in_path(
                projects,
                root,
            )

        self.load_projects()

        if hasattr(self, "load_dashboard"):

            self.load_dashboard()

        self.scan_status.setText(
            f"Scan completed. Projects found: {len(projects)}"
        )

    # ==================================================
    # Scan Failed & Cleanup Worker
    # ==================================================

    def scan_failed(self, error_message):

        self.scan_status.setText(
            f"Scan failed: {error_message}"
        )

        QMessageBox.warning(
            self,
            "Project Scan Failed",
            error_message,
        )

    def cleanup_scan_worker(self):

        self.scan_button.setEnabled(True)

        self.browse_scan_button.setEnabled(True)

        if hasattr(self, "scan_worker") and self.scan_worker is not None:

            self.scan_worker.deleteLater()

            self.scan_worker = None

    # ==================================================
    # Ignore & Restore Projects
    # ==================================================

    def ignore_selected_project(self):

        row = self.projects_table.currentRow()

        if row < 0:

            QMessageBox.information(
                self,
                "No Project Selected",
                "Please select a project from the table first.",
            )

            return

        name_item = self.projects_table.item(row, 0)

        path_item = self.projects_table.item(row, 2)

        if name_item is None or path_item is None:

            return

        project_name = name_item.text()

        project_path = path_item.text()

        answer = QMessageBox.question(
            self,
            "Ignore Project",
            (
                f"Ignore '{project_name}'?\n\n"
                "It will be removed from the project list "
                "and excluded from future scans.\n\n"
                "Your actual project files will NOT be deleted."
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:

            return

        self.project_registry.ignore_project(
            project_path,
            project_name,
        )

        self.load_projects()

        if hasattr(self, "load_dashboard"):

            self.load_dashboard()

        self.scan_status.setText(
            f"Ignored project: {project_name}"
        )

    def restore_ignored_project(self):

        ignored_projects = (
            self.project_registry.get_ignored_projects()
        )

        if not ignored_projects:

            QMessageBox.information(
                self,
                "No Ignored Projects",
                "There are no ignored projects to restore.",
            )

            return

        project_names = [
            f'{project["name"]} — {project["path"]}'
            for project in ignored_projects
        ]

        selected, confirmed = QInputDialog.getItem(
            self,
            "Restore Ignored Project",
            "Select a project to restore:",
            project_names,
            0,
            False,
        )

        if not confirmed or not selected:

            return

        selected_index = project_names.index(selected)

        project = ignored_projects[selected_index]

        self.project_registry.restore_ignored_project(
            project["path"]
        )

        QMessageBox.information(
            self,
            "Project Restored",
            (
                f"'{project['name']}' is no longer ignored.\n\n"
                "Run a scan to discover it again."
            ),
        )

        self.scan_status.setText(
            f"Restored: {project['name']}. Run a scan to rediscover it."
        )

    # ==================================================
    # Export Projects to Excel
    # ==================================================

    def export_projects_to_excel(self):

        projects = (
            self.project_registry
            .get_projects()
        )

        if not projects:

            QMessageBox.information(
                self,
                "No Projects",
                "There are no projects to export."
            )

            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Projects",
            "ubuntu-devtools-projects.xlsx",
            "Excel Files (*.xlsx)"
        )

        if not file_path:

            return

        try:

            workbook = Workbook()

            worksheet = workbook.active

            worksheet.title = "Projects"

            headers = [
                "Name",
                "Type",
                "Path",
                "Confidence",
                "Status",
                "Last Scanned"
            ]

            worksheet.append(headers)

            for project in projects:

                worksheet.append([
                    project.get("name", ""),
                    project.get("project_type", ""),
                    project.get("path", ""),
                    str(project.get("confidence", "")),
                    project.get("status", ""),
                    str(project.get("last_scanned", ""))
                ])

            workbook.save(file_path)

            QMessageBox.information(
                self,
                "Export Successful",
                f"Projects data successfully exported to:\n{file_path}"
            )

        except Exception as error:

            QMessageBox.critical(
                self,
                "Export Failed",
                f"An error occurred while exporting:\n{str(error)}"
            )

    # ==================================================
    # Dashboard Data
    # ==================================================

    def load_dashboard(self):

        projects = (
            self.project_registry
            .get_projects()
        )

        self.project_count_card.value_label.setText(
            str(len(projects))
        )

        running = 0

        for project in projects:

            if project["status"] == "Running":

                running += 1

        self.running_count_card.value_label.setText(
            str(running)
        )

        ports = (
            self.port_manager
            .get_active_ports()
        )

        self.port_count_card.value_label.setText(
            str(len(ports))
        )

        self.dashboard_projects.setRowCount(
            len(projects)
        )

        for row, project in enumerate(projects):

            values = [
                project["name"],
                project["project_type"],
                project["path"],
                project["status"]
            ]

            for column, value in enumerate(values):

                self.dashboard_projects.setItem(
                    row,
                    column,
                    QTableWidgetItem(
                        str(value or "")
                    )
                )

    # ==================================================
    # Projects
    # ==================================================

    def load_projects(self):

        projects = (
            self.project_registry
            .get_projects()
        )

        self.projects_table.setRowCount(len(projects))

        for row, project in enumerate(projects):

            values = [
                project["name"],
                project["project_type"],
                project["path"],
                project["confidence"],
                project["status"],
                project["last_scanned"],
            ]

            for column, value in enumerate(values):

                item = QTableWidgetItem(str(value or ""))

                # Store the database ID with the project name.
                if column == 0:

                    item.setData(
                        Qt.ItemDataRole.UserRole,
                        project["id"],
                    )

                # Show the full path when hovering over the path cell.
                if column == 2:

                    item.setToolTip(str(value or ""))

                self.projects_table.setItem(
                    row,
                    column,
                    item,
                )

    # ==================================================
    # Show Selected Project Path
    # ==================================================

    def show_selected_project_path(self):

        row = self.projects_table.currentRow()

        if row < 0:

            QMessageBox.information(
                self,
                "No Project Selected",
                "Please select a project first."
            )

            return

        path_item = self.projects_table.item(row, 2)

        if path_item is None:

            return

        full_path = path_item.text()

        dialog = QMessageBox(self)

        dialog.setWindowTitle("Project Full Path")

        dialog.setIcon(QMessageBox.Icon.Information)

        dialog.setText("Complete project location:")

        dialog.setInformativeText(full_path)

        # Allow selecting and copying the path with the mouse.
        dialog.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        copy_button = dialog.addButton(
            "Copy Path",
            QMessageBox.ButtonRole.ActionRole
        )

        dialog.addButton(QMessageBox.StandardButton.Close)

        dialog.exec()

        if dialog.clickedButton() == copy_button:

            QApplication.clipboard().setText(full_path)

            QMessageBox.information(
                self,
                "Copied",
                "Project path copied to clipboard."
            )

    # ==================================================
    # Delete Selected Project
    # ==================================================

    def delete_selected_project(self):

        row = self.projects_table.currentRow()

        if row < 0:

            QMessageBox.information(
                self,
                "No Project Selected",
                "Please select a project to delete."
            )

            return

        name_item = self.projects_table.item(row, 0)

        if name_item is None:

            return

        project_id = name_item.data(Qt.ItemDataRole.UserRole)

        project_name = name_item.text()

        if project_id is None:

            QMessageBox.warning(
                self,
                "Error",
                "Could not identify the selected project."
            )

            return

        answer = QMessageBox.question(
            self,
            "Confirm Deletion",
            f'Remove "{project_name}" from Ubuntu DevTools?\n\n'
            "The actual project folder and its files will NOT be deleted.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if answer != QMessageBox.StandardButton.Yes:

            return

        try:

            self.project_registry.remove_project(int(project_id))

            self.load_projects()

            self.load_dashboard()

            QMessageBox.information(
                self,
                "Project Removed",
                f'"{project_name}" has been removed from the project list.'
            )

        except Exception as error:

            QMessageBox.critical(
                self,
                "Deletion Failed",
                f"Could not remove the project:\n{error}"
            )

    # ==================================================
    # Ports
    # ==================================================

    def load_ports(self):

        ports = (
            self.port_manager
            .get_active_ports()
        )

        self.port_table.setRowCount(
            len(ports)
        )

        for row, port in enumerate(ports):

            values = [
                str(port["port"]),
                port["address"],
                port["protocol"],
                str(port["pid"])
                if port["pid"] is not None
                else "-",
                port["process"],
                port["status"]
            ]

            for column, value in enumerate(values):

                self.port_table.setItem(
                    row,
                    column,
                    QTableWidgetItem(
                        value
                    )
                )

        self.process_info.setText(
            "No process selected."
        )

    # ==================================================
    # Search Port
    # ==================================================

    def search_port(self):

        text = (
            self.port_search_field
            .text()
            .strip()
        )

        if not text:

            return

        try:

            port_number = int(text)

        except ValueError:

            return

        port = (
            self.port_manager
            .find_port(port_number)
        )

        if port is None:

            return

        for row in range(
            self.port_table.rowCount()
        ):

            item = self.port_table.item(
                row,
                0
            )

            if (
                item
                and int(item.text()) == port_number
            ):

                self.port_table.selectRow(
                    row
                )

                self.port_table.scrollToItem(
                    item
                )

                return

    # ==================================================
    # Selected Process
    # ==================================================

    def show_selected_process(self):

        selected_rows = (
            self.port_table
            .selectionModel()
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

        if not pid_item:

            return

        pid_text = pid_item.text()

        if pid_text == "-":

            self.process_info.setText(
                "No process information available."
            )

            return

        pid = int(pid_text)

        details = (
            self.port_manager
            .get_process_details(pid)
        )

        if details is None:

            return

        self.process_info.setText(
            f"PID: {details['pid']}   |   "
            f"Process: {details['name']}   |   "
            f"Status: {details['status']}   |   "
            f"User: {details['username']}"
        )

    # ==================================================
    # Process Details
    # ==================================================

    def show_process_details(self):

        selected_rows = (
            self.port_table
            .selectionModel()
            .selectedRows()
        )

        if not selected_rows:

            return

        row = selected_rows[0].row()

        pid_item = self.port_table.item(
            row,
            3
        )

        if (
            not pid_item
            or pid_item.text() == "-"
        ):

            return

        pid = int(
            pid_item.text()
        )

        details = (
            self.port_manager
            .get_process_details(pid)
        )

        if not details:

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
            self.port_table
            .selectionModel()
            .selectedRows()
        )

        if not selected_rows:

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
            not port_item
            or not pid_item
            or not process_item
        ):

            return

        if pid_item.text() == "-":

            return

        port_number = int(
            port_item.text()
        )

        pid = int(
            pid_item.text()
        )

        process_name = process_item.text()

        confirmation = QMessageBox.question(
            self,
            "Confirm Process Termination",
            (
                f"Terminate '{process_name}' "
                f"(PID {pid})?\n\n"
                f"Port: {port_number}"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if confirmation != QMessageBox.Yes:

            return

        success = (
            self.port_manager
            .terminate_process(
                port_number,
                pid
            )
        )

        if success:

            self.load_ports()

            self.load_dashboard()

        else:

            QMessageBox.warning(
                self,
                "Termination Failed",
                f"Could not terminate process {pid}."
            )

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

        #SidebarSubtitle {
            color: #72757e;
            font-size: 11px;
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

        #Navigation::item:hover:!selected {
            background-color: #242629;
            color: #fffffe;
        }

        #Version {
            color: #72757e;
            font-size: 11px;
        }

        #PageTitle {
            font-size: 26px;
            font-weight: bold;
            color: #fffffe;
        }

        #PageSubtitle {
            font-size: 13px;
            color: #94a1b2;
        }

        #SectionTitle {
            font-size: 17px;
            font-weight: bold;
            color: #fffffe;
        }

        #StatCard {
            background-color: #242629;
            border: 1px solid #2b2c34;
            border-radius: 10px;
        }

        #StatTitle {
            color: #94a1b2;
            font-size: 12px;
            font-weight: 500;
        }

        #StatValue {
            color: #fffffe;
            font-size: 26px;
            font-weight: bold;
        }

        #InfoCard {
            background-color: #242629;
            border: 1px solid #2b2c34;
            border-radius: 10px;
        }

        QTableWidget {
            background-color: #242629;
            border: 1px solid #2b2c34;
            border-radius: 8px;
            gridline-color: #2b2c34;
            color: #fffffe;
            selection-background-color: #383a40;
            selection-color: #ffffff;
            outline: none;
        }

        QHeaderView::section {
            background-color: #16161a;
            color: #94a1b2;
            padding: 10px;
            border: none;
            border-bottom: 1px solid #2b2c34;
            font-weight: bold;
        }

        QLineEdit {
            background-color: #242629;
            border: 1px solid #383a40;
            border-radius: 7px;
            padding: 8px 12px;
            color: #fffffe;
        }

        QLineEdit:focus {
            border: 1px solid #2cb67d;
        }

        QComboBox {
            background-color: #242629;
            border: 1px solid #383a40;
            border-radius: 7px;
            padding: 8px 12px;
            color: #fffffe;
        }

        QComboBox:focus {
            border: 1px solid #2cb67d;
        }

        QPushButton {
            background-color: #2cb67d;
            color: #ffffff;
            border: none;
            border-radius: 7px;
            padding: 8px 18px;
            font-weight: 600;
        }

        QPushButton:hover {
            background-color: #259d6c;
        }

        QPushButton:pressed {
            background-color: #1f855b;
        }

        QPushButton:disabled {
            background-color: #3a3d42;
            color: #72757e;
        }

        #ProcessInfo {
            background-color: #242629;
            border: 1px solid #2b2c34;
            border-radius: 7px;
            padding: 12px;
            color: #94a1b2;
        }

        QScrollBar:vertical {
            background: #1e1e24;
            width: 10px;
            margin: 0px;
        }

        QScrollBar::handle:vertical {
            background: #383a40;
            min-height: 20px;
            border-radius: 5px;
        }

        QScrollBar::handle:vertical:hover {
            background: #4a4d55;
        }

        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {
            height: 0px;
        }
        """


# ==================================================
# Run Application
# ==================================================

if __name__ == "__main__":

    app = QApplication(sys.argv)

    window = MainWindow()

    window.show()

    sys.exit(
        app.exec()
    )