import sys
import os
import json
import shutil
import subprocess
import venv
import inspect
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import QThread, Signal
from openpyxl import Workbook
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QPushButton, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView,
    QComboBox, QInputDialog, QFileDialog, QMessageBox, QMenu, QTextEdit,
    QGroupBox, QProgressBar, QCheckBox, QSplitter
)

from plugins.port_manager import PortManager
from core.project_registry import ProjectRegistry
from plugins.workspace_launcher.discovery import ProjectDiscovery

try:
    from plugins.workspace_launcher.analyzer import DependencyAnalyzer
except Exception:
    DependencyAnalyzer = None
try:
    from plugins.workspace_launcher.environment_checker import EnvironmentChecker
except Exception:
    EnvironmentChecker = None
try:
    from plugins.workspace_launcher.environment import EnvironmentManager
except Exception:
    EnvironmentManager = None
try:
    from plugins.workspace_launcher.runner import ProjectRunner
except Exception:
    ProjectRunner = None
try:
    from plugins.workspace_launcher.workspace_analyzer import WorkspaceAnalyzer
except Exception:
    WorkspaceAnalyzer = None


# ==================================================
# Background project scanning
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
            projects = ProjectDiscovery().discover(root_path=self.root_path, mode=self.mode)
            self.scan_completed.emit(projects)
        except Exception as error:
            self.failed.emit(str(error))


class WorkspaceTaskWorker(QThread):
    completed = Signal(str, object)
    failed = Signal(str)

    def __init__(self, task, *args, **kwargs):
        super().__init__()
        self.task = task
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.task(*self.args, **self.kwargs)
            self.completed.emit("", result)
        except Exception as error:
            self.failed.emit(str(error))


class DependencyAnalysisWorker(QThread):
    result_ready = Signal(object)
    error_occurred = Signal(str)

    def __init__(self, window, project, path):
        super().__init__(window)
        self.window = window
        self.project = project
        self.path = Path(path)

    def run(self):
        try:
            window = self.window
            path = self.path
            project = self.project

            # Dependency analysis runs in the background.
            deps, analyzer_outputs = window._dependency_analysis(path)

            rows = []
            project_type = project.get(
                "project_type",
                project.get("type", "Unknown"),
            )

            # Runtime checks also run outside the UI thread.
            rows.extend(window._runtime_checks(path, project_type))

            env_path = path / ".venv"

            rows.append({
                "category": "Environment",
                "name": "Project virtual environment",
                "required": str(env_path),
                "status": "Exists" if env_path.exists() else "Not created",
                "details": (
                    "Project-local Python environment; "
                    "no system-wide pip install will be used."
                ),
            })

            python_exe = env_path / "bin" / "python"

            # Check installed Python packages without blocking the UI.
            for dep in deps:
                name = str(dep.get("name", ""))
                ecosystem = str(
                    dep.get("ecosystem", "python")
                ).lower()

                required = str(
                    dep.get("required", dep.get("version", "Not specified"))
                )

                status = "Detected"
                details = "Found in project manifest / analyzer output"

                if ecosystem in ("python", "py", "") and python_exe.exists():
                    try:
                        normalized = (
                            name.split("[")[0]
                            .split("=")[0]
                            .split("<")[0]
                            .split(">")[0]
                            .strip()
                        )

                        result = subprocess.run(
                            [
                                str(python_exe),
                                "-m",
                                "pip",
                                "show",
                                normalized,
                            ],
                            cwd=str(path),
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )

                        if result.returncode == 0:
                            version_line = next(
                                (
                                    line
                                    for line in result.stdout.splitlines()
                                    if line.startswith("Version:")
                                ),
                                "Version: unknown",
                            )
                            status = "Installed"
                            details = version_line
                        else:
                            status = "MISSING"
                            details = (
                                "Package not installed in project .venv"
                            )

                    except Exception as error:
                        status = "Check"
                        details = str(error)

                rows.append({
                    "category": "Dependency",
                    "name": name,
                    "required": required,
                    "status": status,
                    "details": details,
                })

            self.result_ready.emit({
                "project": project,
                "path": str(path),
                "dependencies": deps,
                "analyzer_outputs": analyzer_outputs,
                "rows": rows,
            })

        except Exception as error:
            self.error_occurred.emit(
                f"{type(error).__name__}: {error}"
            )

# ==================================================
# Main Window
# ==================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ubuntu DevTools")
        self.resize(1250, 820)
        self.port_manager = PortManager()
        self.project_registry = ProjectRegistry()
        self.scan_worker = None
        self.workspace_worker = None
        self.selected_scan_path = None
        self.current_tab_filter = "all"
        self.workspace_project = None
        self.workspace_analysis = None
        self.workspace_dependencies = []
        self.setup_ui()
        self.load_dashboard()

    # -------------------- Main UI --------------------
    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.create_sidebar())
        self.pages = QStackedWidget()
        self.dashboard_page = self.create_dashboard_page()
        self.projects_page = self.create_projects_page()
        self.workspace_page = self.create_workspace_page()
        self.port_page = self.create_port_page()
        for page in (self.dashboard_page, self.projects_page, self.workspace_page, self.port_page):
            self.pages.addWidget(page)
        main_layout.addWidget(self.pages, 1)
        self.setStyleSheet(self.get_stylesheet())

    def create_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 24, 18, 18)
        layout.setSpacing(8)
        logo = QLabel("Ubuntu DevTools")
        logo.setObjectName("Logo")
        subtitle = QLabel("Developer Productivity")
        subtitle.setObjectName("SidebarSubtitle")
        layout.addWidget(logo)
        layout.addWidget(subtitle)
        layout.addSpacing(25)
        self.navigation = QListWidget()
        self.navigation.setObjectName("Navigation")
        for text in ("Dashboard", "Projects", "Workspace Launcher", "Port Manager"):
            self.navigation.addItem(QListWidgetItem(text))
        self.navigation.currentRowChanged.connect(self.change_page)
        layout.addWidget(self.navigation)
        layout.addStretch()
        version = QLabel("Ubuntu DevTools\nv0.1.0")
        version.setObjectName("Version")
        layout.addWidget(version)
        self.navigation.setCurrentRow(0)
        return sidebar

    def change_page(self, index):
        if not hasattr(self, "pages"):
            return

        self.pages.setCurrentIndex(index)

        if index == 0:
            self.load_dashboard()
        elif index == 1:
            self.load_projects()
        elif index == 2:
            self.load_workspace_projects()
        elif index == 3:
            self.load_ports()
    # -------------------- Shared UI helpers --------------------
    @staticmethod
    def create_stat_card(title, value):
        card = QFrame()
        card.setObjectName("StatCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 15, 18, 15)
        title_label = QLabel(title)
        title_label.setObjectName("StatTitle")
        value_label = QLabel(value)
        value_label.setObjectName("StatValue")
        card.value_label = value_label
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return card

    @staticmethod
    def make_table(headers, selection=QTableWidget.SingleSelection):
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(selection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        return table

    # -------------------- Dashboard --------------------
    def create_dashboard_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(35, 30, 35, 30)
        layout.setSpacing(20)
        title = QLabel("Dashboard")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Your development workspace at a glance.")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        cards = QHBoxLayout()
        self.project_count_card = self.create_stat_card("Projects", "0")
        self.running_count_card = self.create_stat_card("Running", "0")
        self.port_count_card = self.create_stat_card("Active Ports", "0")
        for card in (self.project_count_card, self.running_count_card, self.port_count_card):
            cards.addWidget(card)
        layout.addLayout(cards)
        section = QLabel("Your Projects")
        section.setObjectName("SectionTitle")
        layout.addWidget(section)
        self.dashboard_projects = self.make_table(["Project", "Type", "Location", "Status"])
        layout.addWidget(self.dashboard_projects)
        return page

    def load_dashboard(self):
        if not hasattr(self, "dashboard_projects"):
            return
        try:
            projects = self.project_registry.get_projects() or []
        except Exception:
            projects = []
        self.project_count_card.value_label.setText(str(len(projects)))
        self.running_count_card.value_label.setText(str(sum(1 for p in projects if str(p.get("status", "")).lower() == "running")))
        try:
            ports = self.port_manager.get_active_ports() or []
        except Exception:
            ports = []
        self.port_count_card.value_label.setText(str(len(ports)))
        self.dashboard_projects.setRowCount(len(projects))
        for row, project in enumerate(projects):
            vals = [project.get("name", "Unnamed"), project.get("project_type", project.get("type", "Unknown")), project.get("path", ""), project.get("status", "Idle")]
            for col, value in enumerate(vals):
                self.dashboard_projects.setItem(row, col, QTableWidgetItem(str(value or "")))

    # -------------------- Projects --------------------
    def create_projects_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(35, 25, 35, 25)
        layout.setSpacing(13)
        header = QHBoxLayout()
        text_layout = QVBoxLayout()
        title = QLabel("Projects")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Discover, organize and manage your development projects.")
        subtitle.setObjectName("PageSubtitle")
        text_layout.addWidget(title)
        text_layout.addWidget(subtitle)
        self.add_project_button = QPushButton("Add Project")
        self.add_project_button.clicked.connect(self.manually_add_project)
        header.addLayout(text_layout)
        header.addStretch()
        header.addWidget(self.add_project_button)
        layout.addLayout(header)
        stats = QHBoxLayout()
        self.card_total = self.create_stat_card("TOTAL PROJECTS", "0")
        self.card_detected = self.create_stat_card("DETECTED", "0")
        self.card_running = self.create_stat_card("RUNNING", "0")
        for card in (self.card_total, self.card_detected, self.card_running):
            stats.addWidget(card)
        layout.addLayout(stats)
        self.project_search_bar = QLineEdit()
        self.project_search_bar.setPlaceholderText("Search projects by name, type or path...")
        self.project_search_bar.textChanged.connect(self.filter_projects_table)
        layout.addWidget(self.project_search_bar)
        tabs = QHBoxLayout()
        self.btn_tab_all = QPushButton("All Projects")
        self.btn_tab_running = QPushButton("Running")
        self.btn_tab_scanned = QPushButton("Recently Scanned")
        for button, name in ((self.btn_tab_all, "all"), (self.btn_tab_running, "running"), (self.btn_tab_scanned, "scanned")):
            button.setObjectName("TabButton" if name != "all" else "TabButtonActive")
            button.clicked.connect(lambda checked=False, value=name: self.switch_project_tab(value))
            tabs.addWidget(button)
        tabs.addStretch()
        self.more_menu_button = QPushButton("More")
        menu = QMenu(self)
        menu.addAction("Export to Excel", self.export_projects_to_excel)
        menu.addAction("Manage Ignored Projects", self.restore_ignored_project)
        self.more_menu_button.setMenu(menu)
        tabs.addWidget(self.more_menu_button)
        layout.addLayout(tabs)
        self.projects_table = self.make_table(["Name", "Type", "Location", "Status", "Actions"])
        self.projects_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self.projects_table, 1)
        scan_card = QFrame()
        scan_card.setObjectName("ScanCard")
        scan_layout = QVBoxLayout(scan_card)
        scan_layout.setContentsMargins(15, 12, 15, 12)
        self.scan_location_label = QLabel(f"Scan Location: {Path.home()}")
        self.scan_location_label.setObjectName("ScanLocationText")
        controls = QHBoxLayout()
        self.scan_mode_combo = QComboBox()
        self.scan_mode_combo.addItem("Developer Workspace Scan", "workspace")
        self.scan_mode_combo.addItem("Full System Scan", "full")
        self.browse_scan_button = QPushButton("Browse")
        self.browse_scan_button.clicked.connect(self.browse_scan_location)
        self.scan_button = QPushButton("Scan Projects")
        self.scan_button.clicked.connect(self.scan_projects)
        controls.addWidget(self.scan_mode_combo, 2)
        controls.addWidget(self.browse_scan_button)
        controls.addWidget(self.scan_button, 2)
        scan_layout.addWidget(self.scan_location_label)
        scan_layout.addLayout(controls)
        layout.addWidget(scan_card)
        footer = QHBoxLayout()
        self.scan_status = QLabel("Ready to scan.")
        self.scan_status.setObjectName("PageSubtitle")
        self.last_scan_label = QLabel("Last scan: —")
        self.last_scan_label.setObjectName("PageSubtitle")
        footer.addWidget(self.scan_status)
        footer.addStretch()
        footer.addWidget(self.last_scan_label)
        layout.addLayout(footer)
        self.current_tab_filter = "all"
        return page

    def load_projects(self):
        try:
            projects = self.project_registry.get_projects() or []
        except Exception as error:
            QMessageBox.warning(self, "Projects", f"Could not load projects:\n{error}")
            return
        self.projects_table.setRowCount(len(projects))
        detected = running = 0
        for row, project in enumerate(projects):
            name = str(project.get("name", "Unnamed"))
            p_type = str(project.get("project_type", project.get("type", "Unknown")))
            path = str(project.get("path", ""))
            confidence = str(project.get("confidence", "Medium"))
            status = str(project.get("status", "Idle"))
            if confidence.lower() != "manual":
                detected += 1
            if status.lower() == "running":
                running += 1
            name_item = QTableWidgetItem(f"{name}\n   {confidence} confidence")
            name_item.setData(Qt.ItemDataRole.UserRole, project.get("id"))
            name_item.setToolTip(name)
            self.projects_table.setItem(row, 0, name_item)
            self.projects_table.setItem(row, 1, QTableWidgetItem(p_type))
            path_item = QTableWidgetItem(path)
            path_item.setToolTip(path)
            self.projects_table.setItem(row, 2, path_item)
            self.projects_table.setItem(row, 3, QTableWidgetItem(status))
            action_button = QPushButton("⋯")
            action_button.setObjectName("RowActionMenu")
            action_button.setFixedWidth(38)
            action_menu = QMenu(self)
            action_menu.addAction("Detection Details", lambda r=row: self.show_project_detection_details_by_row(r))
            action_menu.addAction("View Full Path", lambda r=row: self.show_selected_project_path_by_row(r))
            action_menu.addAction("Open in Workspace Launcher", lambda r=row: self.open_project_in_workspace(r))
            action_menu.addAction("Ignore Project", lambda r=row: self.ignore_selected_project_by_row(r))
            action_menu.addAction("Delete from Registry", lambda r=row: self.delete_selected_project_by_row(r))
            action_button.setMenu(action_menu)
            self.projects_table.setCellWidget(row, 4, action_button)
        self.card_total.value_label.setText(str(len(projects)))
        self.card_detected.value_label.setText(str(detected))
        self.card_running.value_label.setText(str(running))
        self.filter_projects_table()

    def switch_project_tab(self, tab_type):
        self.current_tab_filter = tab_type
        for button, name in ((self.btn_tab_all, "all"), (self.btn_tab_running, "running"), (self.btn_tab_scanned, "scanned")):
            button.setObjectName("TabButtonActive" if name == tab_type else "TabButton")
        self.setStyleSheet(self.get_stylesheet())
        self.filter_projects_table()

    def filter_projects_table(self):
        if not hasattr(self, "projects_table"):
            return
        query = self.project_search_bar.text().lower().strip()
        for row in range(self.projects_table.rowCount()):
            values = [self.projects_table.item(row, col).text().lower() if self.projects_table.item(row, col) else "" for col in (0, 1, 2, 3)]
            matches_search = not query or any(query in value for value in values)
            status = values[3]
            matches_tab = self.current_tab_filter != "running" or "running" in status
            if self.current_tab_filter == "scanned":
                matches_tab = True
            self.projects_table.setRowHidden(row, not (matches_search and matches_tab))

    def browse_scan_location(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Scan", str(Path.home()))
        if folder:
            self.selected_scan_path = str(Path(folder).resolve())
            self.scan_location_label.setText(f"Scan Location: {self.selected_scan_path}")

    def scan_projects(self):
        mode = self.scan_mode_combo.currentData()
        root = self.selected_scan_path or ("/" if mode == "full" else str(Path.home()))
        self.current_scan_mode = mode
        self.current_scan_root = str(Path(root).resolve())
        self.scan_button.setEnabled(False)
        self.browse_scan_button.setEnabled(False)
        self.scan_status.setText(f"Scanning {self.current_scan_root}…")
        self.scan_worker = ProjectScanWorker(mode, root)
        self.scan_worker.scan_completed.connect(self.scan_finished)
        self.scan_worker.failed.connect(self.scan_failed)
        self.scan_worker.finished.connect(self.cleanup_scan_worker)
        self.scan_worker.start()

    def scan_finished(self, projects):
        root, mode = self.current_scan_root, self.current_scan_mode
        try:
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
            self.load_dashboard()
            self.load_workspace_projects()
            self.last_scan_label.setText("Last scan: " + datetime.now().strftime("%Y-%m-%d %H:%M"))
            self.scan_status.setText(f"Scan completed. {len(projects)} projects found.")
        except Exception as error:
            self.scan_failed(str(error))

    def scan_failed(self, message):
        self.scan_status.setText(f"Scan failed: {message}")
        QMessageBox.warning(self, "Project Scan Failed", message)

    def cleanup_scan_worker(self):
        self.scan_button.setEnabled(True)
        self.browse_scan_button.setEnabled(True)
        if self.scan_worker:
            self.scan_worker.deleteLater()
            self.scan_worker = None

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

    def open_project_in_workspace(self, row):
        self.pages.setCurrentIndex(2)
        self.navigation.setCurrentRow(2)
        item = self.projects_table.item(row, 0)
        if item:
            project_id = item.data(Qt.ItemDataRole.UserRole)
            for index in range(self.workspace_project_combo.count()):
                if self.workspace_project_combo.itemData(index) == project_id:
                    self.workspace_project_combo.setCurrentIndex(index)
                    break
            self.on_workspace_project_changed()

    def show_project_detection_details(self):
        row = self.projects_table.currentRow()
        if row < 0:
            return
        name_item, type_item, path_item, status_item = [self.projects_table.item(row, col) for col in range(4)]
        if not path_item:
            return
        name = name_item.text().split("\n")[0].strip() if name_item else "Unnamed"
        path = path_item.text()
        lines = [f"Name: {name}", f"Project Type: {type_item.text() if type_item else 'Unknown'}", f"Status: {status_item.text() if status_item else 'Unknown'}", f"Root Directory: {path}", ""]
        if not Path(path).is_dir():
            lines.append("Detection result: directory missing.")
        else:
            try:
                result = ProjectDiscovery().detector.detect(path)
                if not result or result.get("type") == "Unknown":
                    lines.append("Current detection result: Not recognized")
                else:
                    lines.append(f"Current detected type: {result.get('type', 'Unknown')}")
                    lines.append("Detected marker files:")
                    lines.extend(f"  • {item}" for item in result.get("files", []))
            except Exception as error:
                lines.append(f"Could not inspect project: {error}")
        QMessageBox.information(self, "Project Detection Details", "\n".join(lines))

    def manually_add_project(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Project Folder", str(Path.home()))
        if not folder:
            return
        path = Path(folder).resolve()
        try:
            result = ProjectDiscovery().detector.detect(str(path))
            detected_type = result.get("type", "Manual") if result else "Manual"
            files = result.get("files", []) if result else []
        except Exception:
            detected_type, files = "Manual", []
        project = {"name": path.name or str(path), "path": str(path), "type": detected_type, "project_type": detected_type, "confidence": "Manual", "files": files}
        try:
            self.project_registry.register_project(project)
            self.load_projects()
            self.load_dashboard()
            self.load_workspace_projects()
        except Exception as error:
            QMessageBox.warning(self, "Add Project Failed", str(error))

    def show_selected_project_path(self):
        row = self.projects_table.currentRow()
        if row >= 0 and self.projects_table.item(row, 2):
            QMessageBox.information(self, "Full Path", self.projects_table.item(row, 2).text())

    def ignore_selected_project(self):
        row = self.projects_table.currentRow()
        if row >= 0 and self.projects_table.item(row, 0) and self.projects_table.item(row, 2):
            name = self.projects_table.item(row, 0).text().split("\n")[0].strip()
            path = self.projects_table.item(row, 2).text()
            try:
                self.project_registry.ignore_project(path, name)
                self.load_projects()
                self.load_workspace_projects()
            except Exception as error:
                QMessageBox.warning(self, "Ignore Project Failed", str(error))

    def restore_ignored_project(self):
        try:
            ignored = self.project_registry.get_ignored_projects() or []
        except Exception as error:
            QMessageBox.warning(self, "Ignored Projects", str(error))
            return
        if not ignored:
            QMessageBox.information(self, "Ignored Projects", "No ignored projects found.")
            return
        names = [f"{p.get('name', 'Unnamed')} — {p.get('path', '')}" for p in ignored]
        selected, ok = QInputDialog.getItem(self, "Restore Project", "Select a project to restore:", names, 0, False)
        if ok and selected:
            project = ignored[names.index(selected)]
            try:
                self.project_registry.restore_ignored_project(project["path"])
                self.load_projects()
                self.load_dashboard()
                self.load_workspace_projects()
            except Exception as error:
                QMessageBox.warning(self, "Restore Failed", str(error))

    def delete_selected_project(self):
        row = self.projects_table.currentRow()
        if row < 0 or not self.projects_table.item(row, 0):
            return
        project_id = self.projects_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        name = self.projects_table.item(row, 0).text().split("\n")[0]
        answer = QMessageBox.question(self, "Remove Project", f"Remove '{name}' from the registry?\nThe project files will not be deleted.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        if project_id is None:
            QMessageBox.warning(self, "Remove Project", "This registry entry has no ID; it cannot be removed safely.")
            return
        try:
            self.project_registry.remove_project(int(project_id))
            self.load_projects()
            self.load_dashboard()
            self.load_workspace_projects()
        except Exception as error:
            QMessageBox.warning(self, "Remove Project Failed", str(error))

    def export_projects_to_excel(self):
        try:
            projects = self.project_registry.get_projects() or []
        except Exception as error:
            QMessageBox.warning(self, "Export Failed", str(error))
            return
        if not projects:
            QMessageBox.information(self, "Export Projects", "There are no projects to export.")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Export Projects", "projects.xlsx", "Excel Files (*.xlsx)")
        if not file_path:
            return
        if not file_path.lower().endswith(".xlsx"):
            file_path += ".xlsx"
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "Projects"
            ws.append(["Name", "Type", "Path", "Confidence", "Status", "Last Scanned"])
            for p in projects:
                ws.append([p.get("name"), p.get("project_type", p.get("type")), p.get("path"), p.get("confidence"), p.get("status"), p.get("last_scanned")])
            wb.save(file_path)
            QMessageBox.information(self, "Export Complete", f"Exported {len(projects)} projects to:\n{file_path}")
        except Exception as error:
            QMessageBox.warning(self, "Export Failed", str(error))

    # -------------------- Workspace Launcher --------------------
    def create_workspace_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(12)
        title = QLabel("Workspace Launcher")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Inspect dependencies and runtimes, prepare a project-local environment, verify it, and launch.")
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        select_group = QGroupBox("Registered Project")
        select_layout = QVBoxLayout(select_group)
        top = QHBoxLayout()
        self.workspace_project_combo = QComboBox()
        self.workspace_project_combo.currentIndexChanged.connect(self.on_workspace_project_changed)
        self.refresh_workspace_button = QPushButton("Refresh Projects")
        self.refresh_workspace_button.clicked.connect(self.load_workspace_projects)
        top.addWidget(self.workspace_project_combo, 1)
        top.addWidget(self.refresh_workspace_button)
        select_layout.addLayout(top)
        self.workspace_path_label = QLabel("Select a registered project.")
        self.workspace_path_label.setWordWrap(True)
        self.workspace_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        select_layout.addWidget(self.workspace_path_label)
        layout.addWidget(select_group)

        action_row = QHBoxLayout()
        self.analyze_workspace_button = QPushButton("Analyze Dependencies & Environment")
        self.analyze_workspace_button.clicked.connect(self.analyze_workspace)
        self.prepare_environment_button = QPushButton("Prepare / Install Missing Dependencies")
        self.prepare_environment_button.clicked.connect(self.prepare_workspace_environment)
        self.verify_workspace_button = QPushButton("Verify Installation")
        self.verify_workspace_button.clicked.connect(self.verify_workspace_environment)
        self.launch_workspace_button = QPushButton("Launch Project")
        self.launch_workspace_button.clicked.connect(self.launch_workspace_project)
        for button in (self.analyze_workspace_button, self.prepare_environment_button, self.verify_workspace_button, self.launch_workspace_button):
            action_row.addWidget(button)
        layout.addLayout(action_row)

        splitter = QSplitter(Qt.Orientation.Vertical)
        dependency_group = QGroupBox("Dependency / Runtime Check")
        dependency_layout = QVBoxLayout(dependency_group)
        self.workspace_dependency_table = self.make_table(["Category", "Name", "Required / Detected", "Status", "Details"])
        self.workspace_dependency_table.setMinimumHeight(180)
        dependency_layout.addWidget(self.workspace_dependency_table)
        log_group = QGroupBox("Workspace Activity")
        log_layout = QVBoxLayout(log_group)
        self.workspace_log = QTextEdit()
        self.workspace_log.setReadOnly(True)
        self.workspace_log.setPlaceholderText("Select a project and run analysis to see dependency, environment, installation and launch details.")
        log_layout.addWidget(self.workspace_log)
        splitter.addWidget(dependency_group)
        splitter.addWidget(log_group)
        splitter.setSizes([330, 220])
        layout.addWidget(splitter, 1)
        self.workspace_progress = QProgressBar()
        self.workspace_progress.setRange(0, 100)
        self.workspace_progress.setValue(0)
        layout.addWidget(self.workspace_progress)
        return page

    def load_workspace_projects(self):
        if not hasattr(self, "workspace_project_combo"):
            return
        current_id = self.workspace_project_combo.currentData()
        self.workspace_project_combo.blockSignals(True)
        self.workspace_project_combo.clear()
        try:
            projects = self.project_registry.get_projects() or []
        except Exception as error:
            projects = []
            self.workspace_log_append(f"Could not read project registry: {error}")
        for project in projects:
            name = project.get("name", "Unnamed")
            path = project.get("path", "")
            label = f"{name}  —  {path}"
            self.workspace_project_combo.addItem(label, project.get("id"))
            self.workspace_project_combo.setItemData(self.workspace_project_combo.count() - 1, project, Qt.ItemDataRole.UserRole + 1)
        if current_id is not None:
            for i in range(self.workspace_project_combo.count()):
                if self.workspace_project_combo.itemData(i) == current_id:
                    self.workspace_project_combo.setCurrentIndex(i)
                    break
        self.workspace_project_combo.blockSignals(False)
        self.on_workspace_project_changed()

    def get_selected_workspace_project(self):
        index = self.workspace_project_combo.currentIndex()
        if index < 0:
            return None
        project = self.workspace_project_combo.itemData(index, Qt.ItemDataRole.UserRole + 1)
        if isinstance(project, dict):
            return project
        project_id = self.workspace_project_combo.itemData(index)
        try:
            for item in self.project_registry.get_projects() or []:
                if item.get("id") == project_id:
                    return item
        except Exception:
            pass
        return None

    def on_workspace_project_changed(self, *_):
        if not hasattr(self, "workspace_path_label"):
            return
        project = self.get_selected_workspace_project()
        self.workspace_project = project
        self.workspace_analysis = None
        self.workspace_dependencies = []
        if not project:
            self.workspace_path_label.setText("No registered project available. Add or scan projects first.")
            return
        path = Path(str(project.get("path", ""))).expanduser()
        self.workspace_path_label.setText(f"Project: {project.get('name', 'Unnamed')}\nPath: {path}\nType: {project.get('project_type', project.get('type', 'Unknown'))}")
        self.workspace_dependency_table.setRowCount(0)

    def workspace_log_append(self, text):
        if hasattr(self, "workspace_log"):
            self.workspace_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {text}")

    @staticmethod
    def _call_compatible(method, *args, **kwargs):
        """Call a backend method with only supported keyword arguments."""
        try:
            signature = inspect.signature(method)
            if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values()):
                return method(*args, **kwargs)
            allowed = {key: value for key, value in kwargs.items() if key in signature.parameters}
            return method(*args, **allowed)
        except (TypeError, ValueError):
            return method(*args)

    @staticmethod
    def _normalise_dependencies(value):
        if value is None:
            return []
        if isinstance(value, dict):
            for key in ("dependencies", "packages", "requirements", "items", "results"):
                if key in value and isinstance(value[key], (list, tuple, dict)):
                    return MainWindow._normalise_dependencies(value[key])
            result = []
            for name, details in value.items():
                if isinstance(details, dict):
                    item = dict(details)
                    item.setdefault("name", name)
                    result.append(item)
                else:
                    result.append({"name": str(name), "required": str(details)})
            return result
        if isinstance(value, (list, tuple, set)):
            result = []
            for item in value:
                if isinstance(item, dict):
                    result.append(dict(item))
                else:
                    result.append({"name": str(item)})
            return result
        if isinstance(value, str):
            return [{"name": line.strip()} for line in value.splitlines() if line.strip()]
        return []

    def _dependency_analysis(self, project_path):
        """Use the project's installed analyzer when available; add manifest fallback."""
        outputs = []
        if DependencyAnalyzer:
            try:
                analyzer = DependencyAnalyzer()
                for method_name in ("analyze_and_verify", "analyze", "resolve_dependencies"):
                    method = getattr(analyzer, method_name, None)
                    if not callable(method):
                        continue
                    try:
                        result = self._call_compatible(method, str(project_path))
                        outputs.append((method_name, result))
                        if result:
                            break
                    except Exception as error:
                        outputs.append((method_name + " error", str(error)))
            except Exception as error:
                outputs.append(("Analyzer initialization", str(error)))
        deps = []
        for method_name, result in outputs:
            if "error" in method_name.lower() or not result:
                continue

            # analyze() returns project analysis metadata, not dependencies.
            if method_name == "analyze":
                continue

            # Extract dependencies from the structured verification result.
            if isinstance(result, dict):
                if result.get("status") == "error":
                    outputs.append((
                        "Analyzer error",
                        result.get("message", "Dependency analysis failed."),
                    ))
                    continue

                if "dependencies" in result:
                    dependency_data = result["dependencies"]
                elif method_name == "resolve_dependencies":
                    dependency_data = result
                else:
                    continue
            else:
                dependency_data = result

            normalized = self._normalise_dependencies(dependency_data)

            if normalized:
                deps = normalized
                break
        # Manifest fallback helps when an analyzer returns no normalized package list.
        manifest_names = ["requirements.txt", "pyproject.toml", "Pipfile", "package.json", "package-lock.json", "composer.json", "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "*.csproj"]
        for manifest in manifest_names:
            matches = list(project_path.glob(manifest)) if "*" in manifest else ([project_path / manifest] if (project_path / manifest).is_file() else [])
            for file_path in matches:
                try:
                    if file_path.name == "requirements.txt":
                        for line in file_path.read_text(errors="ignore").splitlines():
                            line = line.strip()
                            if line and not line.startswith(("#", "-")):
                                deps.append({"name": line.split(";")[0].strip(), "required": line, "ecosystem": "python"})
                    elif file_path.name == "package.json":
                        data = json.loads(file_path.read_text(errors="ignore"))
                        for section in ("dependencies", "devDependencies"):
                            for name, version in data.get(section, {}).items():
                                deps.append({"name": name, "required": str(version), "ecosystem": "node"})
                    elif file_path.name == "composer.json":
                        data = json.loads(file_path.read_text(errors="ignore"))
                        for section in ("require", "require-dev"):
                            for name, version in data.get(section, {}).items():
                                if name != "php":
                                    deps.append({"name": name, "required": str(version), "ecosystem": "php"})
                    elif file_path.name == "Cargo.toml":
                        in_deps = False
                        for line in file_path.read_text(errors="ignore").splitlines():
                            stripped = line.strip()
                            if stripped.startswith("["):
                                in_deps = stripped in ("[dependencies]", "[dev-dependencies]")
                            elif in_deps and "=" in stripped and not stripped.startswith("#"):
                                name, version = stripped.split("=", 1)
                                deps.append({"name": name.strip(), "required": version.strip().strip('"'), "ecosystem": "rust"})
                except Exception as error:
                    outputs.append((f"Read {file_path.name}", str(error)))
        # Deduplicate by ecosystem/name while preserving manifest requirements.
        unique = {}
        for dep in deps:
            name = str(dep.get("name", dep.get("package", dep.get("dependency", "")))).strip()
            if not name:
                continue
            key = (str(dep.get("ecosystem", "" )).lower(), name.lower())
            unique[key] = {**dep, "name": name}
        return list(unique.values()), outputs

    @staticmethod
    def _runtime_checks(project_path, project_type):
        checks = []
        p = project_path
        files = {x.name for x in p.iterdir()} if p.is_dir() else set()
        t = str(project_type or "").lower()
        runtimes = []
        if "python" in t or any(x in files for x in ("requirements.txt", "pyproject.toml", "Pipfile", "main.py", "app.py")):
            runtimes.append(("Python", "python3", "python --version"))
        if "node" in t or "javascript" in t or "typescript" in t or "package.json" in files:
            runtimes.append(("Node.js", "node", "node --version"))
            runtimes.append(("npm", "npm", "npm --version"))
        if "php" in t or "composer.json" in files or "artisan" in files:
            runtimes.append(("PHP", "php", "php --version"))
            if "composer.json" in files:
                runtimes.append(("Composer", "composer", "composer --version"))
        if "java" in t or any(x in files for x in ("pom.xml", "build.gradle", "build.gradle.kts")):
            runtimes.append(("Java JDK", "java", "java -version"))
            if "pom.xml" in files:
                runtimes.append(("Maven", "mvn", "mvn --version"))
            if "build.gradle" in files or "build.gradle.kts" in files:
                runtimes.append(("Gradle", "gradle", "gradle --version"))
        if "go" in t or "go.mod" in files:
            runtimes.append(("Go", "go", "go version"))
        if "rust" in t or "Cargo.toml" in files:
            runtimes.append(("Rust/Cargo", "cargo", "cargo --version"))
        if "dotnet" in t or "c#" in t or any(n.endswith(".csproj") for n in files):
            runtimes.append((".NET SDK", "dotnet", "dotnet --info"))
        if "docker" in t or "Dockerfile" in files or "docker-compose.yml" in files or "compose.yaml" in files:
            runtimes.append(("Docker", "docker", "docker --version"))
        seen = set()
        for label, command, version_cmd in runtimes:
            if command in seen:
                continue
            seen.add(command)
            location = shutil.which(command)
            if not location:
                checks.append({"category": "Runtime", "name": label, "required": command, "status": "MISSING", "details": f"'{command}' was not found on PATH. Install the system runtime/SDK before running this project."})
            else:
                try:
                    result = subprocess.run(version_cmd, shell=True, cwd=str(p), capture_output=True, text=True, timeout=8)
                    output = (result.stdout or result.stderr).strip().splitlines()
                    checks.append({"category": "Runtime", "name": label, "required": command, "status": "Available" if result.returncode == 0 else "Check", "details": (output[0] if output else location)[:220]})
                except Exception as error:
                    checks.append({"category": "Runtime", "name": label, "required": command, "status": "Check", "details": str(error)})
        return checks

    def analyze_workspace(self):
        project = self.get_selected_workspace_project()

        if not project:
            QMessageBox.information(
                self,
                "Workspace Launcher",
                "Select a registered project first.",
            )
            return

        path = Path(str(project.get("path", ""))).expanduser()

        if not path.is_dir():
            QMessageBox.warning(
                self,
                "Project Missing",
                f"Project directory does not exist:\n{path}",
            )
            return

        # Prevent multiple simultaneous analyses.
        if (
            hasattr(self, "analysis_worker")
            and self.analysis_worker.isRunning()
        ):
            return

        self.workspace_project = project
        self.workspace_log.clear()
        self.workspace_dependency_table.setRowCount(0)

        self.workspace_progress.setRange(0, 0)
        self.analyze_workspace_button.setEnabled(False)

        self.workspace_log_append(
            f"Analyzing {project.get('name')} at {path}"
        )
        self.workspace_log_append(
            "Scanning dependencies and checking the project environment..."
        )

        # Run the expensive work in a background thread.
        self.analysis_worker = DependencyAnalysisWorker(
            self,
            project,
            path,
        )

        self.analysis_worker.result_ready.connect(
            self._on_workspace_analysis_complete
        )
        self.analysis_worker.error_occurred.connect(
            self._on_workspace_analysis_error
        )
        self.analysis_worker.finished.connect(
            self._on_workspace_worker_finished
        )

        self.analysis_worker.start()


    def _on_workspace_analysis_complete(self, result):
        deps = result["dependencies"]
        rows = result["rows"]
        analyzer_outputs = result["analyzer_outputs"]

        self.workspace_dependencies = deps

        self.workspace_analysis = {
            "project": result["project"],
            "path": result["path"],
            "dependencies": deps,
            "analyzer_outputs": analyzer_outputs,
        }

        self._populate_workspace_rows(rows)

        self.workspace_progress.setRange(0, 100)
        self.workspace_progress.setValue(100)

        missing_count = sum(
            1 for row in rows
            if row.get("status") == "MISSING"
        )

        self.workspace_log_append(
            f"Analysis complete: {len(deps)} dependency entries; "
            f"{missing_count} missing runtime/package checks."
        )

        for method, output in analyzer_outputs:
            if "error" in method.lower() or isinstance(output, str):
                self.workspace_log_append(
                    f"{method}: {str(output)[:500]}"
                )

        self.workspace_log_append(
            "Review missing runtimes. The app will not install system "
            "SDKs or run system-wide pip installs automatically."
        )


    def _on_workspace_analysis_error(self, message):
        self.workspace_progress.setRange(0, 100)
        self.workspace_progress.setValue(0)

        self.workspace_log_append(
            f"Analysis failed: {message}"
        )

        QMessageBox.warning(
            self,
            "Dependency Analysis Failed",
            message,
        )


    def _on_workspace_worker_finished(self):
        self.analyze_workspace_button.setEnabled(True)

        if self.workspace_progress.maximum() == 0:
            self.workspace_progress.setRange(0, 100)
            self.workspace_progress.setValue(0)

    def _populate_workspace_rows(self, rows):
        self.workspace_dependency_table.setRowCount(len(rows))
        for row_index, data in enumerate(rows):
            values = [data.get("category", ""), data.get("name", ""), data.get("required", ""), data.get("status", ""), data.get("details", "")]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setToolTip(str(value or ""))
                self.workspace_dependency_table.setItem(row_index, col, item)
        self.workspace_dependency_table.resizeRowsToContents()

    def _python_dependencies(self):
        deps = []
        for item in self.workspace_dependencies:
            ecosystem = str(item.get("ecosystem", "python")).lower()
            if ecosystem not in ("python", "py", ""):
                continue
            requirement = str(item.get("required", item.get("name", ""))).strip()
            name = str(item.get("name", "")).strip()
            if requirement and name:
                # requirements.txt entries can contain version pins/extras; preserve requirement expression.
                deps.append(requirement if any(op in requirement for op in ("==", ">=", "<=", "~=", "!=", "<", ">", "[")) else name)
        req_file = self.workspace_analysis and Path(self.workspace_analysis["path"]) / "requirements.txt"
        if req_file and req_file.is_file():
            try:
                for line in req_file.read_text(errors="ignore").splitlines():
                    line = line.strip()
                    if line and not line.startswith(("#", "-")):
                        deps.append(line)
            except Exception:
                pass
        # Preserve order and remove duplicates.
        return list(dict.fromkeys(deps))

    def prepare_workspace_environment(self):
        project = self.get_selected_workspace_project()
        if not project:
            QMessageBox.information(self, "Workspace Launcher", "Select a registered project first.")
            return
        path = Path(str(project.get("path", ""))).expanduser()
        if not path.is_dir():
            QMessageBox.warning(self, "Project Missing", f"Project directory does not exist:\n{path}")
            return
        if self.workspace_analysis is None or self.workspace_analysis.get("path") != str(path):
            self.analyze_workspace()
        if self.workspace_analysis is None:
            return
        missing_runtimes = []
        for row in range(self.workspace_dependency_table.rowCount()):
            if self.workspace_dependency_table.item(row, 0) and self.workspace_dependency_table.item(row, 0).text() == "Runtime":
                if self.workspace_dependency_table.item(row, 3) and self.workspace_dependency_table.item(row, 3).text() == "MISSING":
                    missing_runtimes.append(self.workspace_dependency_table.item(row, 1).text())
        python_deps = self._python_dependencies()
        if not python_deps and not (path / "requirements.txt").is_file():
            QMessageBox.information(self, "No Python Dependencies", "No Python package requirements were detected. Missing system runtimes, if any, must be installed separately.")
            return
        env_path = path / ".venv"
        message = [f"Project: {project.get('name')}\nPath: {path}", f"Python packages to install: {len(python_deps)}", "", "A virtual environment will be created/reused at:", str(env_path), "", "No system-wide pip installation will be performed."]
        if missing_runtimes:
            message.extend(["", "Missing system runtimes (not installed by this action):", *[f"• {name}" for name in missing_runtimes]])
        if python_deps:
            message.extend(["", "Package requirements:", *[f"• {item}" for item in python_deps[:30]]])
            if len(python_deps) > 30:
                message.append(f"…and {len(python_deps) - 30} more")
        answer = QMessageBox.question(self, "Confirm Project-local Installation", "\n".join(message) + "\n\nContinue?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            self.workspace_log_append("Installation cancelled by user.")
            return
        self._set_workspace_busy(True)
        self.workspace_progress.setValue(0)
        self.workspace_log_append("Preparing project-local environment…")
        self.workspace_worker = WorkspaceTaskWorker(self._install_project_python_dependencies, str(path), python_deps)
        self.workspace_worker.completed.connect(self._workspace_install_completed)
        self.workspace_worker.failed.connect(self._workspace_task_failed)
        self.workspace_worker.finished.connect(lambda: self._set_workspace_busy(False))
        self.workspace_worker.start()

    @staticmethod
    def _install_project_python_dependencies(project_path, dependencies):
        import shutil
        import time
        from pathlib import Path
        import subprocess

        path = Path(project_path).expanduser().resolve()

        if not path.is_dir():
            raise RuntimeError(
                f"Project directory does not exist: {path}"
            )

        env_path = path / ".venv"
        python_exe = env_path / "bin" / "python"

        def run_command(command, timeout=30):
            return subprocess.run(
                command,
                cwd=str(path),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )

        def valid_environment():
            if not python_exe.is_file():
                return False

            result = run_command([
                str(python_exe),
                "-c",
                (
                    "import sys; "
                    "print(sys.prefix); "
                    "print(sys.base_prefix)"
                ),
            ])

            if result.returncode != 0:
                return False

            lines = result.stdout.strip().splitlines()

            if len(lines) < 2 or lines[0] == lines[1]:
                return False

            pip_result = run_command([
                str(python_exe),
                "-m",
                "pip",
                "--version",
            ])

            return pip_result.returncode == 0

        # Reuse the environment only if it is genuinely functional.
        if env_path.exists() and not valid_environment():
            # Preserve the broken environment instead of deleting it.
            backup_path = path / (
                f".venv.invalid-{int(time.time())}"
            )

            if backup_path.exists():
                backup_path = path / (
                    f".venv.invalid-{int(time.time())}-{os.getpid()}"
                )

            shutil.move(str(env_path), str(backup_path))

        if not env_path.exists():
            # Never use sys.executable here: in a packaged app it may
            # point to the PyInstaller executable rather than Python.
            candidates = [
                "/usr/bin/python3",
                "/usr/local/bin/python3",
                "/bin/python3",
            ]

            host_python = None

            for candidate in candidates:
                if not Path(candidate).is_file():
                    continue

                check = subprocess.run(
                    [
                        candidate,
                        "-c",
                        "import sys, venv; print(sys.version)",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )

                if check.returncode == 0:
                    host_python = candidate
                    break

            if not host_python:
                raise RuntimeError(
                    "A working system Python 3 installation with "
                    "the venv module was not found. "
                    "Expected /usr/bin/python3 or /usr/local/bin/python3."
                )

            result = subprocess.run(
                [
                    host_python,
                    "-m",
                    "venv",
                    str(env_path),
                ],
                cwd=str(path),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    "Virtual environment creation failed:\n"
                    + (result.stderr or result.stdout)[-5000:]
                )

        # Validate the newly created or reused environment.
        if not valid_environment():
            raise RuntimeError(
                "The project virtual environment was created, "
                "but its Python interpreter or pip is not working: "
                f"{python_exe}"
            )

        install_output = "No Python package requirements found."

        if dependencies:
            upgrade = run_command(
                [
                    str(python_exe),
                    "-m",
                    "pip",
                    "install",
                    "--upgrade",
                    "pip",
                ],
                timeout=180,
            )

            if upgrade.returncode != 0:
                raise RuntimeError(
                    "Could not upgrade pip:\n"
                    + (upgrade.stderr or upgrade.stdout)[-5000:]
                )

            result = run_command(
                [
                    str(python_exe),
                    "-m",
                    "pip",
                    "install",
                    *dependencies,
                ],
                timeout=1800,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    "Dependency installation failed:\n"
                    + (result.stderr or result.stdout)[-5000:]
                )

            install_output = result.stdout[-5000:]

        verify = run_command(
            [
                str(python_exe),
                "-m",
                "pip",
                "check",
            ],
            timeout=120,
        )

        return {
            "path": str(env_path),
            "install_output": install_output,
            "verification": (
                verify.stdout + verify.stderr
            ).strip(),
            "verification_ok": verify.returncode == 0,
        }

    def _workspace_install_completed(self, _message, result):
        self.workspace_progress.setValue(100)
        self.workspace_log_append(f"Environment ready: {result.get('path')}")
        self.workspace_log_append("Installation output:\n" + (result.get("install_output") or "(no output)"))
        if result.get("verification_ok"):
            self.workspace_log_append("Dependency verification passed: pip check found no broken requirements.")
            QMessageBox.information(self, "Environment Prepared", "Project-local environment is ready and dependency verification passed. Run Analyze / Verify to refresh the table.")
        else:
            self.workspace_log_append("Dependency verification reported issues:\n" + result.get("verification", "Unknown verification error"))
            QMessageBox.warning(self, "Verification Warning", "The environment was prepared, but pip check reported dependency issues. Review Workspace Activity.")
        self._set_workspace_busy(False)
        self.analyze_workspace()

    def _workspace_task_failed(self, error):
        self.workspace_progress.setValue(0)
        self.workspace_log_append("Operation failed: " + error)
        QMessageBox.critical(self, "Workspace Operation Failed", error)
        self._set_workspace_busy(False)

    def verify_workspace_environment(self):
        project = self.get_selected_workspace_project()
        if not project:
            QMessageBox.information(self, "Workspace Launcher", "Select a registered project first.")
            return
        path = Path(str(project.get("path", ""))).expanduser()
        self.workspace_log_append("Verifying environment and dependencies…")
        self.analyze_workspace()
        env_python = path / ".venv" / "bin" / "python"
        if env_python.exists():
            try:
                check = subprocess.run([str(env_python), "-m", "pip", "check"], cwd=str(path), capture_output=True, text=True, timeout=120)
                if check.returncode == 0:
                    self.workspace_log_append("VERIFIED: pip check passed in project .venv.")
                    QMessageBox.information(self, "Verification Passed", "Project-local Python environment exists and pip check passed.")
                else:
                    detail = (check.stdout + check.stderr).strip()
                    self.workspace_log_append("VERIFICATION ISSUES:\n" + detail)
                    QMessageBox.warning(self, "Verification Issues", detail or "pip check found dependency issues.")
            except Exception as error:
                QMessageBox.warning(self, "Verification Failed", str(error))
        else:
            self.workspace_log_append("No project-local .venv found. Use Prepare / Install Missing Dependencies if this project needs Python packages.")
            QMessageBox.information(self, "Environment Not Found", "No project-local .venv exists yet. Analyze the runtime checks, then prepare the environment if needed.")

    def launch_workspace_project(self):
        project = self.get_selected_workspace_project()
        if not project:
            QMessageBox.information(self, "Workspace Launcher", "Select a registered project first.")
            return
        path = Path(str(project.get("path", ""))).expanduser()
        if not path.is_dir():
            QMessageBox.warning(self, "Project Missing", f"Project directory does not exist:\n{path}")
            return
        if self.workspace_analysis is None or self.workspace_analysis.get("path") != str(path):
            self.analyze_workspace()
        # Prevent accidental launch when a detected system runtime is missing.
        missing = []
        for row in range(self.workspace_dependency_table.rowCount()):
            cat = self.workspace_dependency_table.item(row, 0)
            status = self.workspace_dependency_table.item(row, 3)
            name = self.workspace_dependency_table.item(row, 1)
            if cat and status and name and cat.text() == "Runtime" and status.text() == "MISSING":
                missing.append(name.text())
        if missing:
            answer = QMessageBox.question(self, "Runtime Missing", "These runtimes were not found:\n" + "\n".join(f"• {x}" for x in missing) + "\n\nTry launching anyway?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        if ProjectRunner:
            answer = QMessageBox.question(self, "Launch Project", f"Launch '{project.get('name')}'?\n\n{path}", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            try:
                runner = ProjectRunner()
                result = self._call_compatible(runner.launch, project)
                self.workspace_log_append(f"Launch request sent to ProjectRunner. Result: {result}")
                QMessageBox.information(self, "Launch Requested", f"ProjectRunner launch request completed.\n\n{result if result is not None else 'Check the project terminal/process for output.'}")
                return
            except Exception as error:
                self.workspace_log_append(f"ProjectRunner failed: {error}")
                QMessageBox.warning(self, "Runner Failed", f"ProjectRunner could not launch the project:\n{error}\n\nYou can try a detected entry point manually from the project folder.")
                return
        self._fallback_launch(path)

    def _fallback_launch(self, path):
        candidates = []
        env_python = path / ".venv" / "bin" / "python"
        if env_python.exists():
            for name in ("main.py", "app.py", "run.py"):
                if (path / name).is_file():
                    candidates.append([str(env_python), str(path / name)])
            for name in ("main.py", "app.py"):
                if (path / "backend" / name).is_file():
                    candidates.append([str(env_python), str(path / "backend" / name)])
        if (path / "package.json").is_file() and shutil.which("npm"):
            candidates.append(["npm", "run", "dev"])
        if (path / "run.sh").is_file():
            candidates.append(["bash", str(path / "run.sh")])
        if (path / "run.bat").is_file():
            QMessageBox.information(self, "Windows Script Detected", "This project contains run.bat, which is a Windows batch file and cannot run directly on Ubuntu. Use a Linux run.sh or configure the project runner.")
            return
        if not candidates:
            QMessageBox.warning(self, "No Launch Entry Point", "No safe default entry point was detected. Add/configure the project runner for this project type.")
            return
        labels = [" ".join(command) for command in candidates]
        selected, ok = QInputDialog.getItem(self, "Choose Launch Command", "Detected launch options:", labels, 0, False)
        if not ok or not selected:
            return
        command = candidates[labels.index(selected)]
        try:
            subprocess.Popen(command, cwd=str(path), start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            QMessageBox.information(self, "Launch Started", f"Started:\n{' '.join(command)}\n\nWorking directory:\n{path}")
            self.workspace_log_append(f"Started process: {' '.join(command)}")
        except Exception as error:
            QMessageBox.critical(self, "Launch Failed", str(error))

    def _set_workspace_busy(self, busy):
        for button in (self.analyze_workspace_button, self.prepare_environment_button, self.verify_workspace_button, self.launch_workspace_button, self.refresh_workspace_button):
            button.setEnabled(not busy)

    # -------------------- Port Manager --------------------
    def create_port_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(35, 30, 35, 30)
        layout.setSpacing(15)
        title = QLabel("Port Manager")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Monitor and manage active network ports.")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        search = QHBoxLayout()
        self.port_search_field = QLineEdit()
        self.port_search_field.setPlaceholderText("Enter port number…")
        search_button = QPushButton("Search")
        search_button.clicked.connect(self.search_port)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.load_ports)
        search.addWidget(self.port_search_field, 1)
        search.addWidget(search_button)
        search.addWidget(refresh_button)
        layout.addLayout(search)
        self.port_table = self.make_table(["Port", "Address", "Protocol", "PID", "Process", "Status"])
        self.port_table.itemSelectionChanged.connect(self.show_selected_process)
        layout.addWidget(self.port_table, 1)
        self.process_info = QLabel("No process selected.")
        self.process_info.setObjectName("ProcessInfo")
        layout.addWidget(self.process_info)
        buttons = QHBoxLayout()
        buttons.addStretch()
        details_button = QPushButton("Process Details")
        details_button.clicked.connect(self.show_process_details)
        kill_button = QPushButton("Kill Process")
        kill_button.clicked.connect(self.kill_selected_process)
        buttons.addWidget(details_button)
        buttons.addWidget(kill_button)
        layout.addLayout(buttons)
        return page

    def load_ports(self):
        try:
            ports = self.port_manager.get_active_ports() or []
        except Exception as error:
            QMessageBox.warning(self, "Port Manager", f"Could not load ports:\n{error}")
            return
        self.port_table.setRowCount(len(ports))
        for row, port in enumerate(ports):
            values = [str(port.get("port", "")), str(port.get("address", "")), str(port.get("protocol", "")), str(port.get("pid") if port.get("pid") is not None else "-"), str(port.get("process", "")), str(port.get("status", ""))]
            for col, value in enumerate(values):
                self.port_table.setItem(row, col, QTableWidgetItem(value))
        self.process_info.setText("No process selected.")

    def search_port(self):
        text = self.port_search_field.text().strip()
        if not text:
            return
        if not text.isdigit():
            QMessageBox.information(self, "Search Port", "Enter a valid numeric port number.")
            return
        port_number = int(text)
        try:
            self.port_manager.find_port(port_number)
        except Exception:
            pass
        for row in range(self.port_table.rowCount()):
            item = self.port_table.item(row, 0)
            if item and item.text() == str(port_number):
                self.port_table.selectRow(row)
                self.port_table.scrollToItem(item)
                return
        QMessageBox.information(self, "Search Port", f"Port {port_number} was not found in the current list.")

    def show_selected_process(self):
        selected = self.port_table.selectionModel().selectedRows()
        if not selected:
            self.process_info.setText("No process selected.")
            return
        row = selected[0].row()
        pid_item = self.port_table.item(row, 3)
        if not pid_item or pid_item.text() == "-":
            self.process_info.setText("No process information available.")
            return
        try:
            details = self.port_manager.get_process_details(int(pid_item.text()))
        except Exception as error:
            self.process_info.setText(f"Could not read process details: {error}")
            return
        if details:
            self.process_info.setText(f"PID: {details.get('pid')}   |   Process: {details.get('name')}   |   Status: {details.get('status')}   |   User: {details.get('username')}")

    def show_process_details(self):
        selected = self.port_table.selectionModel().selectedRows()
        if not selected:
            QMessageBox.information(self, "Process Details", "Select a process first.")
            return
        row = selected[0].row()
        pid_item = self.port_table.item(row, 3)
        if not pid_item or pid_item.text() == "-":
            QMessageBox.information(self, "Process Details", "No PID is available for this port.")
            return
        try:
            details = self.port_manager.get_process_details(int(pid_item.text()))
        except Exception as error:
            QMessageBox.warning(self, "Process Details", str(error))
            return
        if not details:
            QMessageBox.information(self, "Process Details", "Process details are unavailable.")
            return
        message = "\n".join(f"{key.replace('_', ' ').title()}: {value}" for key, value in details.items())
        QMessageBox.information(self, "Process Details", message)

    def kill_selected_process(self):
        selected = self.port_table.selectionModel().selectedRows()
        if not selected:
            QMessageBox.information(self, "Kill Process", "Select a process first.")
            return
        row = selected[0].row()
        port_item, pid_item, process_item = self.port_table.item(row, 0), self.port_table.item(row, 3), self.port_table.item(row, 4)
        if not port_item or not pid_item or not process_item or pid_item.text() == "-":
            QMessageBox.information(self, "Kill Process", "A valid PID is not available for the selected port.")
            return
        port, pid, name = int(port_item.text()), int(pid_item.text()), process_item.text()
        answer = QMessageBox.question(self, "Confirm Process Termination", f"Terminate '{name}' (PID {pid})?\n\nPort: {port}\nThis may stop an application using this port.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        try:
            success = self.port_manager.terminate_process(port, pid)
        except Exception as error:
            QMessageBox.warning(self, "Termination Failed", str(error))
            return
        if success:
            self.load_ports()
            self.load_dashboard()
        else:
            QMessageBox.warning(self, "Termination Failed", f"Could not terminate process {pid}. It may require elevated permissions or may have already exited.")

    # -------------------- Styling --------------------
    def get_stylesheet(self):
        return """
        QMainWindow { background-color: #1e1e24; color: #e0e0e0; }
        QWidget { color: #e0e0e0; font-family: 'Segoe UI', Ubuntu, sans-serif; }
        #Sidebar { background-color: #16161a; border-right: 1px solid #2b2c34; }
        #Logo { color: #ffffff; font-size: 20px; font-weight: bold; }
        #SidebarSubtitle, #PageSubtitle { color: #9a9da7; font-size: 12px; }
        #Navigation { background: transparent; border: none; color: #c0c5ce; font-size: 14px; outline: none; }
        #Navigation::item { padding: 12px; border-radius: 8px; margin-bottom: 4px; }
        #Navigation::item:selected { background-color: #2cb67d; color: #ffffff; font-weight: bold; }
        #PageTitle { font-size: 24px; font-weight: bold; color: #fffffe; }
        #StatCard, #ScanCard, #InfoCard { background-color: #242629; border: 1px solid #383a40; border-radius: 10px; }
        #StatTitle, #SectionTitle { color: #fffffe; font-size: 15px; font-weight: bold; }
        #StatTitle { color: #9a9da7; font-size: 11px; }
        #StatValue { color: #fffffe; font-size: 22px; font-weight: bold; }
        #TabButton { background-color: transparent; color: #c0c5ce; border: none; padding: 6px 14px; font-weight: 600; }
        #TabButtonActive { background-color: #2cb67d; color: #ffffff; border: none; border-radius: 6px; padding: 6px 14px; font-weight: bold; }
        #RowActionMenu { background-color: transparent; color: #c0c5ce; font-weight: bold; border: none; }
        #RowActionMenu:hover { color: #ffffff; background-color: #383a40; border-radius: 4px; }
        QLineEdit, QComboBox { background-color: #242629; border: 1px solid #383a40; border-radius: 7px; padding: 8px 12px; color: #fffffe; }
        QPushButton { background-color: #2cb67d; color: #ffffff; border: none; border-radius: 7px; padding: 8px 12px; font-weight: 600; }
        QPushButton:hover { background-color: #259d6c; }
        QPushButton:disabled { background-color: #42464d; color: #a0a0a0; }
        #ProcessInfo { background-color: #242629; border: 1px solid #383a40; border-radius: 7px; padding: 12px; color: #c0c5ce; }
        QTableWidget, QTextEdit { background-color: #242629; border: 1px solid #383a40; border-radius: 8px; gridline-color: #383a40; color: #fffffe; selection-background-color: #246d55; }
        QHeaderView::section { background-color: #16161a; color: #c0c5ce; padding: 9px; border: none; border-bottom: 1px solid #383a40; font-weight: bold; }
        QGroupBox { border: 1px solid #383a40; border-radius: 8px; margin-top: 10px; padding-top: 10px; font-weight: bold; }
        QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #c0c5ce; }
        QProgressBar { border: 1px solid #383a40; border-radius: 5px; text-align: center; background: #242629; }
        QProgressBar::chunk { background-color: #2cb67d; border-radius: 4px; }
        QMenu { background-color: #242629; color: #ffffff; border: 1px solid #383a40; }
        QMenu::item:selected { background-color: #2cb67d; }
        """


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())