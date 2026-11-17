import sys
import os
import json
import shutil
import subprocess
import inspect
import re
import threading
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QPushButton, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView,
    QComboBox, QInputDialog, QFileDialog, QMessageBox, QMenu, QTextEdit,
    QGroupBox, QProgressBar, QSplitter, QCheckBox, QAbstractItemView
)
from openpyxl import Workbook

from plugins.port_manager import PortManager
from core.project_registry import ProjectRegistry
from plugins.workspace_launcher.discovery import ProjectDiscovery
from plugins.project_cache_cleaner import ProjectCacheCleaner
from plugins.docker_manager import DockerManager
try:
    from plugins.workspace_launcher.analyzer import DependencyAnalyzer
except Exception:
    DependencyAnalyzer = None


# ==================================================
# Utility: locate a usable system Python interpreter
# ==================================================
def _find_system_python():
    """Return a Python interpreter that can create venvs.

    When frozen (PyInstaller), sys.executable is the app binary, not python.
    """
    if not getattr(sys, "frozen", False):
        return sys.executable

    candidates = [
        shutil.which("python3"),
        shutil.which("python"),
        "/usr/bin/python3",
        "/usr/local/bin/python3",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError(
        "No system Python interpreter found. Please install python3 "
        "and python3-venv (sudo apt install python3 python3-venv)."
    )


# ==================================================
# Background workers
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
            projects = ProjectDiscovery().discover(
                root_path=self.root_path, mode=self.mode
            )
            self.scan_completed.emit(projects)
        except Exception as error:
            self.failed.emit(str(error))


class WorkspaceTaskWorker(QThread):
    completed = Signal(str, object)
    failed = Signal(str)
    log = Signal(str)
    progress = Signal(int, str)

    def __init__(self, task, *args, **kwargs):
        super().__init__()
        self.task = task
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.task(
                *self.args,
                log_callback=self.log.emit,
                progress_callback=self.progress.emit,
                **self.kwargs,
            )
            self.completed.emit("", result)
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}")


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

            deps, analyzer_outputs = window._dependency_analysis(path)
            rows = []

            project_type = project.get(
                "project_type", project.get("type", "Unknown")
            )

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

            for dep in deps:
                name = str(dep.get("name", ""))
                ecosystem = str(dep.get("ecosystem", "python")).lower()
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
                            [str(python_exe), "-m", "pip", "show", normalized],
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
            self.error_occurred.emit(f"{type(error).__name__}: {error}")


class VerifyEnvironmentWorker(QThread):
    """Run `pip check` off the UI thread."""
    completed = Signal(bool, str)

    def __init__(self, python_exe, cwd):
        super().__init__()
        self.python_exe = str(python_exe)
        self.cwd = str(cwd)

    def run(self):
        try:
            result = subprocess.run(
                [self.python_exe, "-m", "pip", "check"],
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=180,
            )
            ok = result.returncode == 0
            detail = (result.stdout + result.stderr).strip()
            self.completed.emit(ok, detail)
        except Exception as error:
            self.completed.emit(False, str(error))


class CacheScanWorker(QThread):
    """Scan a project directory for cache / build artefacts."""
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, cleaner, project_path):
        super().__init__()
        self.cleaner = cleaner
        self.project_path = project_path

    def run(self):
        try:
            results = self.cleaner.scan_project(self.project_path)
            self.completed.emit(results)
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}")


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
        self.cache_cleaner = ProjectCacheCleaner()
        self.docker_manager = DockerManager()
        self.cache_project_path = None
        self.cache_scan_results = []

        self.scan_worker = None
        self.workspace_worker = None
        self.analysis_worker = None
        self.analysis_worker_active = False
        self.verify_worker = None
        self.pending_workspace_action = None
        self.cache_scan_worker = None

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
        self.cache_cleaner_page = self.create_cache_cleaner_page()
        self.docker_page = self.create_docker_page()
        for page in (
            self.dashboard_page,
            self.projects_page,
            self.workspace_page,
            self.port_page,
            self.cache_cleaner_page,
            self.docker_page,
        ):
            self.pages.addWidget(page)
            self.pages.addWidget(page)
        main_layout.addWidget(self.pages, 1)
        self.setStyleSheet(self.get_stylesheet())

    def _workspace_install_progress(self, percentage, package):
        if percentage < 0:
            self.workspace_progress.setRange(0, 0)
            self.workspace_progress.setFormat(
                f"{package}…" if package else "Working…"
            )
            return
        self.workspace_progress.setRange(0, 100)
        self.workspace_progress.setValue(percentage)
        if package:
            self.workspace_progress.setFormat(f"{package} — {percentage}%")
        else:
            self.workspace_progress.setFormat("%p%")

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

        for text in (
            "Dashboard",
            "Projects",
            "Workspace Launcher",
            "Port Manager",
            "Project Cache Cleaner",
            "Docker Manager",
        ):
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
        elif index == 4:
            pass
        elif index == 5:
            self.refresh_docker_dashboard()

    def create_docker_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(15)

        # ---------------- Header ----------------
        header = QHBoxLayout()

        title = QLabel("Docker Manager")
        title.setStyleSheet("font-size: 25px; font-weight: bold;")

        self.docker_refresh_button = QPushButton("Refresh")
        self.docker_refresh_button.clicked.connect(
            self.refresh_docker_dashboard
        )

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.docker_refresh_button)

        layout.addLayout(header)

        description = QLabel(
            "Manage containers, images and Docker resources."
        )
        layout.addWidget(description)

        # ---------------- Docker Status ----------------
        self.docker_status_label = QLabel(
            "Checking Docker status..."
        )
        self.docker_status_label.setStyleSheet(
            "font-size: 14px; font-weight: bold; padding: 8px;"
        )

        self.docker_stats_label = QLabel(
            "Containers: 0 | Running: 0 | Stopped: 0 | "
            "Images: 0 | Volumes: 0"
        )
        self.docker_stats_label.setStyleSheet(
            "font-size: 13px; padding: 8px;"
        )

        layout.addWidget(self.docker_status_label)
        layout.addWidget(self.docker_stats_label)

        # ---------------- Search and Filter ----------------
        filter_layout = QHBoxLayout()

        self.docker_search_input = QLineEdit()
        self.docker_search_input.setPlaceholderText(
            "Search containers by name, ID or image..."
        )
        self.docker_search_input.textChanged.connect(
            self.filter_docker_containers
        )

        self.docker_status_filter = QComboBox()
        self.docker_status_filter.addItems([
            "All Containers",
            "Running",
            "Stopped"
        ])
        self.docker_status_filter.currentTextChanged.connect(
            self.filter_docker_containers
        )

        filter_layout.addWidget(self.docker_search_input, 3)
        filter_layout.addWidget(self.docker_status_filter, 1)

        layout.addLayout(filter_layout)

        # ---------------- Container Table ----------------
        self.docker_container_table = QTableWidget()
        self.docker_container_table.setColumnCount(5)

        self.docker_container_table.setHorizontalHeaderLabels([
            "Container ID",
            "Name",
            "Image",
            "Status",
            "Ports"
        ])

        self.docker_container_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )

        self.docker_container_table.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )

        self.docker_container_table.setSelectionBehavior(
            QAbstractItemView.SelectRows
        )

        self.docker_container_table.setSelectionMode(
            QAbstractItemView.SingleSelection
        )

        self.docker_container_table.setAlternatingRowColors(True)

        self.docker_container_table.itemSelectionChanged.connect(
            self.update_docker_action_buttons
        )

        layout.addWidget(self.docker_container_table, 1)

        # ---------------- Container Actions ----------------
        action_label = QLabel("Container Actions")
        action_label.setStyleSheet(
            "font-size: 15px; font-weight: bold;"
        )

        action_layout = QHBoxLayout()

        self.docker_start_button = QPushButton("Start")
        self.docker_stop_button = QPushButton("Stop")
        self.docker_restart_button = QPushButton("Restart")
        self.docker_remove_button = QPushButton("Remove")

        self.docker_start_button.clicked.connect(
            lambda: self.perform_container_action("start")
        )

        self.docker_stop_button.clicked.connect(
            lambda: self.perform_container_action("stop")
        )

        self.docker_restart_button.clicked.connect(
            lambda: self.perform_container_action("restart")
        )

        self.docker_remove_button.clicked.connect(
            lambda: self.perform_container_action("remove")
        )

        action_layout.addWidget(self.docker_start_button)
        action_layout.addWidget(self.docker_stop_button)
        action_layout.addWidget(self.docker_restart_button)
        action_layout.addWidget(self.docker_remove_button)

        layout.addWidget(action_label)
        layout.addLayout(action_layout)

        self.update_docker_action_buttons()

        return page


    def refresh_docker_dashboard(self):
        summary = self.docker_manager.get_dashboard_summary()

        status = summary["status"]["status"]

        if status == "running":
            self.docker_status_label.setText(
                f"Docker Engine: Running | "
                f"Version: {summary['status'].get('server_version', 'Unknown')}"
            )

        elif status == "not_installed":
            self.docker_status_label.setText(
                "Docker is not installed."
            )

        else:
            self.docker_status_label.setText(
                f"Docker Status: {status}"
            )

        containers = summary.get("containers", {})

        self.docker_stats_label.setText(
            f"Containers: {containers.get('total', 0)} | "
            f"Running: {containers.get('running', 0)} | "
            f"Stopped: {containers.get('stopped', 0)} | "
            f"Images: {summary.get('images', 0)} | "
            f"Volumes: {summary.get('volumes', 0)}"
        )

        self.docker_container_table.setRowCount(0)

        if not summary.get("available"):
            self.update_docker_action_buttons()
            return

        result = self.docker_manager.get_containers()

        if not result["success"]:
            self.docker_status_label.setText(
                f"Docker Error: {result['error']}"
            )
            self.update_docker_action_buttons()
            return

        for container in result["containers"]:
            row = self.docker_container_table.rowCount()
            self.docker_container_table.insertRow(row)

            values = [
                container["id"],
                container["name"],
                container["image"],
                container["status"],
                container["ports"]
            ]

            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))

                if column == 0:
                    item.setData(Qt.UserRole, container["id"])

                if column == 3:
                    item.setData(Qt.UserRole, container["state"])

                self.docker_container_table.setItem(
                    row, column, item
                )

        self.filter_docker_containers()
        self.update_docker_action_buttons()


    def filter_docker_containers(self):
        search_text = self.docker_search_input.text().strip().lower()
        selected_filter = self.docker_status_filter.currentText()

        for row in range(self.docker_container_table.rowCount()):
            container_id = self.docker_container_table.item(row, 0).text().lower()
            name = self.docker_container_table.item(row, 1).text().lower()
            image = self.docker_container_table.item(row, 2).text().lower()

            state_item = self.docker_container_table.item(row, 3)
            state = state_item.data(Qt.UserRole).lower()

            matches_search = (
                search_text in container_id
                or search_text in name
                or search_text in image
            )

            matches_filter = (
                selected_filter == "All Containers"
                or (selected_filter == "Running" and state == "running")
                or (selected_filter == "Stopped" and state != "running")
            )

            self.docker_container_table.setRowHidden(
                row,
                not (matches_search and matches_filter)
            )

        self.update_docker_action_buttons()


    def update_docker_action_buttons(self):
        table = getattr(self, "docker_container_table", None)

        if table is None:
            return

        selected_rows = table.selectionModel().selectedRows()

        if not selected_rows:
            self.docker_start_button.setEnabled(False)
            self.docker_stop_button.setEnabled(False)
            self.docker_restart_button.setEnabled(False)
            self.docker_remove_button.setEnabled(False)
            return

        row = selected_rows[0].row()

        state_item = table.item(row, 3)

        if state_item is None:
            return

        state = state_item.data(Qt.UserRole).lower()
        is_running = state == "running"

        self.docker_start_button.setEnabled(not is_running)
        self.docker_stop_button.setEnabled(is_running)
        self.docker_restart_button.setEnabled(is_running)
        self.docker_remove_button.setEnabled(not is_running)

    def get_selected_docker_container(self):
        selected_rows = (
            self.docker_container_table.selectionModel().selectedRows()
        )

        if not selected_rows:
            return None

        row = selected_rows[0].row()

        item = self.docker_container_table.item(row, 0)

        if item is None:
            return None

        return item.data(Qt.UserRole)

    def perform_container_action(self, action):
        container_id = self.get_selected_docker_container()

        if not container_id:
            QMessageBox.warning(
                self,
                "No Container Selected",
                "Please select a container first."
            )
            return

        if action == "remove":
            reply = QMessageBox.question(
                self,
                "Remove Container",
                f"Are you sure you want to remove container {container_id}?\n\n"
                "This action cannot be undone.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if reply != QMessageBox.Yes:
                return

        if action == "start":
            result = self.docker_manager.start_container(container_id)

        elif action == "stop":
            result = self.docker_manager.stop_container(container_id)

        elif action == "restart":
            result = self.docker_manager.restart_container(container_id)

        elif action == "remove":
            result = self.docker_manager.remove_container(
                container_id,
                force=False
            )

        else:
            return

        if result["success"]:
            QMessageBox.information(
                self,
                "Docker Manager",
                f"Container {action} operation completed successfully."
            )

            self.refresh_docker_dashboard()

        else:
            QMessageBox.critical(
                self,
                "Docker Operation Failed",
                result.get("error") or "Unknown Docker error."
            )

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
        for card in (
            self.project_count_card,
            self.running_count_card,
            self.port_count_card,
        ):
            cards.addWidget(card)
        layout.addLayout(cards)
        section = QLabel("Your Projects")
        section.setObjectName("SectionTitle")
        layout.addWidget(section)
        self.dashboard_projects = self.make_table(
            ["Project", "Type", "Location", "Status"]
        )
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
        self.running_count_card.value_label.setText(
            str(
                sum(
                    1
                    for p in projects
                    if str(p.get("status", "")).lower() == "running"
                )
            )
        )
        try:
            ports = self.port_manager.get_active_ports() or []
        except Exception:
            ports = []
        self.port_count_card.value_label.setText(str(len(ports)))
        self.dashboard_projects.setRowCount(len(projects))
        for row, project in enumerate(projects):
            vals = [
                project.get("name", "Unnamed"),
                project.get("project_type", project.get("type", "Unknown")),
                project.get("path", ""),
                project.get("status", "Idle"),
            ]
            for col, value in enumerate(vals):
                self.dashboard_projects.setItem(
                    row, col, QTableWidgetItem(str(value or ""))
                )

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
        subtitle = QLabel(
            "Discover, organize and manage your development projects."
        )
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
        self.project_search_bar.setPlaceholderText(
            "Search projects by name, type or path..."
        )
        self.project_search_bar.textChanged.connect(
            self.filter_projects_table
        )
        layout.addWidget(self.project_search_bar)

        tabs = QHBoxLayout()
        self.btn_tab_all = QPushButton("All Projects")
        self.btn_tab_scanned = QPushButton("Recently Scanned")
        for button, name in (
            (self.btn_tab_all, "all"),
            (self.btn_tab_scanned, "scanned"),
        ):
            button.setObjectName(
                "TabButton" if name != "all" else "TabButtonActive"
            )
            button.clicked.connect(
                lambda checked=False, value=name: self.switch_project_tab(value)
            )
            tabs.addWidget(button)
        tabs.addStretch()
        self.more_menu_button = QPushButton("More")
        menu = QMenu(self)
        menu.addAction("Export to Excel", self.export_projects_to_excel)
        menu.addAction(
            "Manage Ignored Projects", self.restore_ignored_project
        )
        self.more_menu_button.setMenu(menu)
        tabs.addWidget(self.more_menu_button)
        layout.addLayout(tabs)

        self.projects_table = self.make_table(
            ["Name", "Type", "Location", "Status", "Actions"]
        )
        self.projects_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeToContents
        )
        layout.addWidget(self.projects_table, 1)

        scan_card = QFrame()
        scan_card.setObjectName("ScanCard")
        scan_layout = QVBoxLayout(scan_card)
        scan_layout.setContentsMargins(15, 12, 15, 12)
        self.scan_location_label = QLabel(
            f"Scan Location: {Path.home()}"
        )
        self.scan_location_label.setObjectName("ScanLocationText")
        controls = QHBoxLayout()
        self.scan_mode_combo = QComboBox()
        self.scan_mode_combo.addItem(
            "Developer Workspace Scan", "workspace"
        )
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
            QMessageBox.warning(
                self, "Projects", f"Could not load projects:\n{error}"
            )
            return
        self.projects_table.setRowCount(len(projects))
        detected = running = 0
        for row, project in enumerate(projects):
            name = str(project.get("name", "Unnamed"))
            p_type = str(
                project.get("project_type", project.get("type", "Unknown"))
            )
            path = str(project.get("path", ""))
            confidence = str(project.get("confidence", "Medium"))
            status = str(project.get("status", "Idle"))
            if confidence.lower() != "manual":
                detected += 1
            if status.lower() == "running":
                running += 1
            name_item = QTableWidgetItem(
                f"{name}\n   {confidence} confidence"
            )
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
            action_menu.addAction(
                "Detection Details",
                lambda r=row: self.show_project_detection_details_by_row(r),
            )
            action_menu.addAction(
                "View Full Path",
                lambda r=row: self.show_selected_project_path_by_row(r),
            )
            action_menu.addAction(
                "Open in Workspace Launcher",
                lambda r=row: self.open_project_in_workspace(r),
            )
            action_menu.addAction(
                "Ignore Project",
                lambda r=row: self.ignore_selected_project_by_row(r),
            )
            action_menu.addAction(
                "Delete from Registry",
                lambda r=row: self.delete_selected_project_by_row(r),
            )
            action_button.setMenu(action_menu)
            self.projects_table.setCellWidget(row, 4, action_button)
        self.card_total.value_label.setText(str(len(projects)))
        self.card_detected.value_label.setText(str(detected))
        self.card_running.value_label.setText(str(running))
        self.filter_projects_table()

    def switch_project_tab(self, tab_type):
        self.current_tab_filter = tab_type
        for button, name in (
            (self.btn_tab_all, "all"),
            (self.btn_tab_scanned, "scanned"),
        ):
            button.setObjectName(
                "TabButtonActive" if name == tab_type else "TabButton"
            )
        self.setStyleSheet(self.get_stylesheet())
        self.filter_projects_table()

    def filter_projects_table(self):
        if not hasattr(self, "projects_table"):
            return
        query = self.project_search_bar.text().lower().strip()
        for row in range(self.projects_table.rowCount()):
            values = [
                self.projects_table.item(row, col).text().lower()
                if self.projects_table.item(row, col)
                else ""
                for col in (0, 1, 2, 3)
            ]
            matches_search = not query or any(
                query in value for value in values
            )
            status = values[3]
            matches_tab = (
                self.current_tab_filter != "running"
                or "running" in status
            )
            if self.current_tab_filter == "scanned":
                matches_tab = True
            self.projects_table.setRowHidden(
                row, not (matches_search and matches_tab)
            )

    def browse_scan_location(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder to Scan", str(Path.home())
        )
        if folder:
            self.selected_scan_path = str(Path(folder).resolve())
            self.scan_location_label.setText(
                f"Scan Location: {self.selected_scan_path}"
            )

    def scan_projects(self):
        mode = self.scan_mode_combo.currentData()
        root = self.selected_scan_path or (
            "/" if mode == "full" else str(Path.home())
        )
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
                    self.scan_status.setText(
                        "No projects found. Existing registry preserved."
                    )
                    self.load_projects()
                    return
            else:
                self.project_registry.sync_projects_in_path(projects, root)
            self.load_projects()
            self.load_dashboard()
            self.load_workspace_projects()
            self.last_scan_label.setText(
                "Last scan: "
                + datetime.now().strftime("%Y-%m-%d %H:%M")
            )
            self.scan_status.setText(
                f"Scan completed. {len(projects)} projects found."
            )
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
                if (
                    self.workspace_project_combo.itemData(index)
                    == project_id
                ):
                    self.workspace_project_combo.setCurrentIndex(index)
                    break
            self.on_workspace_project_changed()

    def show_project_detection_details(self):
        row = self.projects_table.currentRow()
        if row < 0:
            return
        name_item, type_item, path_item, status_item = [
            self.projects_table.item(row, col) for col in range(4)
        ]
        if not path_item:
            return
        name = (
            name_item.text().split("\n")[0].strip()
            if name_item
            else "Unnamed"
        )
        path = path_item.text()
        lines = [
            f"Name: {name}",
            f"Project Type: {type_item.text() if type_item else 'Unknown'}",
            f"Status: {status_item.text() if status_item else 'Unknown'}",
            f"Root Directory: {path}",
            "",
        ]
        if not Path(path).is_dir():
            lines.append("Detection result: directory missing.")
        else:
            try:
                result = ProjectDiscovery().detector.detect(path)
                if not result or result.get("type") == "Unknown":
                    lines.append("Current detection result: Not recognized")
                else:
                    lines.append(
                        f"Current detected type: {result.get('type', 'Unknown')}"
                    )
                    lines.append("Detected marker files:")
                    lines.extend(
                        f"  • {item}" for item in result.get("files", [])
                    )
            except Exception as error:
                lines.append(f"Could not inspect project: {error}")
        QMessageBox.information(
            self, "Project Detection Details", "\n".join(lines)
        )

    def manually_add_project(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Project Folder", str(Path.home())
        )
        if not folder:
            return
        path = Path(folder).resolve()
        try:
            result = ProjectDiscovery().detector.detect(str(path))
            detected_type = (
                result.get("type", "Manual") if result else "Manual"
            )
            files = result.get("files", []) if result else []
        except Exception:
            detected_type, files = "Manual", []
        project = {
            "name": path.name or str(path),
            "path": str(path),
            "type": detected_type,
            "project_type": detected_type,
            "confidence": "Manual",
            "files": files,
        }
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
            QMessageBox.information(
                self, "Full Path", self.projects_table.item(row, 2).text()
            )

    def ignore_selected_project(self):
        row = self.projects_table.currentRow()
        if (
            row >= 0
            and self.projects_table.item(row, 0)
            and self.projects_table.item(row, 2)
        ):
            name = (
                self.projects_table.item(row, 0)
                .text()
                .split("\n")[0]
                .strip()
            )
            path = self.projects_table.item(row, 2).text()
            try:
                self.project_registry.ignore_project(path, name)
                self.load_projects()
                self.load_workspace_projects()
            except Exception as error:
                QMessageBox.warning(
                    self, "Ignore Project Failed", str(error)
                )

    def restore_ignored_project(self):
        try:
            ignored = self.project_registry.get_ignored_projects() or []
        except Exception as error:
            QMessageBox.warning(self, "Ignored Projects", str(error))
            return
        if not ignored:
            QMessageBox.information(
                self, "Ignored Projects", "No ignored projects found."
            )
            return
        names = [
            f"{p.get('name', 'Unnamed')} — {p.get('path', '')}"
            for p in ignored
        ]
        selected, ok = QInputDialog.getItem(
            self,
            "Restore Project",
            "Select a project to restore:",
            names,
            0,
            False,
        )
        if ok and selected:
            project = ignored[names.index(selected)]
            try:
                self.project_registry.restore_ignored_project(
                    project["path"]
                )
                self.load_projects()
                self.load_dashboard()
                self.load_workspace_projects()
            except Exception as error:
                QMessageBox.warning(self, "Restore Failed", str(error))

    def delete_selected_project(self):
        row = self.projects_table.currentRow()
        if row < 0 or not self.projects_table.item(row, 0):
            return
        project_id = self.projects_table.item(row, 0).data(
            Qt.ItemDataRole.UserRole
        )
        name = self.projects_table.item(row, 0).text().split("\n")[0]
        answer = QMessageBox.question(
            self,
            "Remove Project",
            f"Remove '{name}' from the registry?\nThe project files will not be deleted.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        if project_id is None:
            QMessageBox.warning(
                self,
                "Remove Project",
                "This registry entry has no ID; it cannot be removed safely.",
            )
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
            QMessageBox.information(
                self, "Export Projects", "There are no projects to export."
            )
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Projects", "projects.xlsx", "Excel Files (*.xlsx)"
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".xlsx"):
            file_path += ".xlsx"
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "Projects"
            ws.append(
                [
                    "Name",
                    "Type",
                    "Path",
                    "Confidence",
                    "Status",
                    "Last Scanned",
                ]
            )
            for p in projects:
                ws.append(
                    [
                        p.get("name"),
                        p.get("project_type", p.get("type")),
                        p.get("path"),
                        p.get("confidence"),
                        p.get("status"),
                        p.get("last_scanned"),
                    ]
                )
            wb.save(file_path)
            QMessageBox.information(
                self,
                "Export Complete",
                f"Exported {len(projects)} projects to:\n{file_path}",
            )
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
        subtitle = QLabel(
            "Inspect dependencies and runtimes, prepare a project-local "
            "environment, verify it, and launch."
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        select_group = QGroupBox("Registered Project")
        select_layout = QVBoxLayout(select_group)
        top = QHBoxLayout()
        self.workspace_project_combo = QComboBox()
        self.workspace_project_combo.currentIndexChanged.connect(
            self.on_workspace_project_changed
        )
        self.refresh_workspace_button = QPushButton("Refresh Projects")
        self.refresh_workspace_button.clicked.connect(
            self.load_workspace_projects
        )
        top.addWidget(self.workspace_project_combo, 1)
        top.addWidget(self.refresh_workspace_button)
        select_layout.addLayout(top)
        self.workspace_path_label = QLabel("Select a registered project.")
        self.workspace_path_label.setWordWrap(True)
        self.workspace_path_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        select_layout.addWidget(self.workspace_path_label)
        layout.addWidget(select_group)

        action_row = QHBoxLayout()
        self.analyze_workspace_button = QPushButton(
            "Analyze Dependencies & Environment"
        )
        self.analyze_workspace_button.clicked.connect(self.analyze_workspace)
        self.prepare_environment_button = QPushButton(
            "Prepare / Install Missing Dependencies"
        )
        self.prepare_environment_button.clicked.connect(
            self.prepare_workspace_environment
        )
        self.verify_workspace_button = QPushButton("Verify Installation")
        self.verify_workspace_button.clicked.connect(
            self.verify_workspace_environment
        )
        self.launch_workspace_button = QPushButton("Launch Project")
        self.launch_workspace_button.clicked.connect(
            self.launch_workspace_project
        )
        for button in (
            self.analyze_workspace_button,
            self.prepare_environment_button,
            self.verify_workspace_button,
            self.launch_workspace_button,
        ):
            action_row.addWidget(button)
        layout.addLayout(action_row)

        splitter = QSplitter(Qt.Orientation.Vertical)
        dependency_group = QGroupBox("Dependency / Runtime Check")
        dependency_layout = QVBoxLayout(dependency_group)
        self.workspace_dependency_table = self.make_table(
            ["Category", "Name", "Required / Detected", "Status", "Details"]
        )
        self.workspace_dependency_table.setMinimumHeight(180)
        dependency_layout.addWidget(self.workspace_dependency_table)
        log_group = QGroupBox("Workspace Activity")
        log_layout = QVBoxLayout(log_group)
        self.workspace_log = QTextEdit()
        self.workspace_log.setReadOnly(True)
        self.workspace_log.setPlaceholderText(
            "Select a project and run analysis to see dependency, "
            "environment, installation and launch details."
        )
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
            self.workspace_log_append(
                f"Could not read project registry: {error}"
            )
        for project in projects:
            name = project.get("name", "Unnamed")
            path = project.get("path", "")
            label = f"{name}  —  {path}"
            self.workspace_project_combo.addItem(label, project.get("id"))
            self.workspace_project_combo.setItemData(
                self.workspace_project_combo.count() - 1,
                project,
                Qt.ItemDataRole.UserRole + 1,
            )
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
        project = self.workspace_project_combo.itemData(
            index, Qt.ItemDataRole.UserRole + 1
        )
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
        self.pending_workspace_action = None
        project = self.get_selected_workspace_project()
        self.workspace_project = project
        self.workspace_analysis = None
        self.workspace_dependencies = []
        if not project:
            self.workspace_path_label.setText(
                "No registered project available. Add or scan projects first."
            )
            self.workspace_dependency_table.setRowCount(0)
            return
        path = Path(str(project.get("path", ""))).expanduser()
        self.workspace_path_label.setText(
            f"Project: {project.get('name', 'Unnamed')}\n"
            f"Path: {path}\n"
            f"Type: {project.get('project_type', project.get('type', 'Unknown'))}"
        )
        self.workspace_dependency_table.setRowCount(0)

    def workspace_log_append(self, text):
        if hasattr(self, "workspace_log"):
            self.workspace_log.append(
                f"[{datetime.now().strftime('%H:%M:%S')}] {text}"
            )

    @staticmethod
    def _call_compatible(method, *args, **kwargs):
        """Call a backend method with only supported keyword arguments."""
        try:
            signature = inspect.signature(method)
            if any(
                p.kind == inspect.Parameter.VAR_KEYWORD
                for p in signature.parameters.values()
            ):
                return method(*args, **kwargs)
            allowed = {
                key: value
                for key, value in kwargs.items()
                if key in signature.parameters
            }
            return method(*args, **allowed)
        except (TypeError, ValueError):
            return method(*args)

    @staticmethod
    def _normalise_dependencies(value):
        if value is None:
            return []
        if isinstance(value, dict):
            for key in (
                "dependencies",
                "packages",
                "requirements",
                "items",
                "results",
            ):
                if key in value and isinstance(
                    value[key], (list, tuple, dict)
                ):
                    return MainWindow._normalise_dependencies(value[key])
            result = []
            for name, details in value.items():
                if isinstance(details, dict):
                    item = dict(details)
                    item.setdefault("name", name)
                    result.append(item)
                else:
                    result.append(
                        {"name": str(name), "required": str(details)}
                    )
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
            return [
                {"name": line.strip()}
                for line in value.splitlines()
                if line.strip()
            ]
        return []

    def _dependency_analysis(self, project_path):
        """Use the project's installed analyzer when available; add manifest fallback."""
        outputs = []
        if DependencyAnalyzer:
            try:
                analyzer = DependencyAnalyzer()
                for method_name in (
                    "analyze_and_verify",
                    "analyze",
                    "resolve_dependencies",
                ):
                    method = getattr(analyzer, method_name, None)
                    if not callable(method):
                        continue
                    try:
                        result = self._call_compatible(
                            method, str(project_path)
                        )
                        outputs.append((method_name, result))
                        if result:
                            break
                    except Exception as error:
                        outputs.append(
                            (method_name + " error", str(error))
                        )
            except Exception as error:
                outputs.append(("Analyzer initialization", str(error)))
        deps = []
        for method_name, result in outputs:
            if "error" in method_name.lower() or not result:
                continue
            if method_name == "analyze":
                continue
            if isinstance(result, dict):
                if result.get("status") == "error":
                    outputs.append(
                        (
                            "Analyzer error",
                            result.get(
                                "message", "Dependency analysis failed."
                            ),
                        )
                    )
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

        manifest_names = [
            "requirements.txt",
            "pyproject.toml",
            "Pipfile",
            "package.json",
            "package-lock.json",
            "composer.json",
            "Cargo.toml",
            "go.mod",
            "pom.xml",
            "build.gradle",
            "*.csproj",
        ]
        for manifest in manifest_names:
            matches = (
                list(project_path.glob(manifest))
                if "*" in manifest
                else (
                    [project_path / manifest]
                    if (project_path / manifest).is_file()
                    else []
                )
            )
            for file_path in matches:
                try:
                    if file_path.name == "requirements.txt":
                        for line in file_path.read_text(
                            errors="ignore"
                        ).splitlines():
                            line = line.strip()
                            if line and not line.startswith(("#", "-")):
                                deps.append(
                                    {
                                        "name": line.split(";")[0].strip(),
                                        "required": line,
                                        "ecosystem": "python",
                                    }
                                )
                    elif file_path.name == "package.json":
                        data = json.loads(
                            file_path.read_text(errors="ignore")
                        )
                        for section in ("dependencies", "devDependencies"):
                            for name, version in data.get(
                                section, {}
                            ).items():
                                deps.append(
                                    {
                                        "name": name,
                                        "required": str(version),
                                        "ecosystem": "node",
                                    }
                                )
                    elif file_path.name == "composer.json":
                        data = json.loads(
                            file_path.read_text(errors="ignore")
                        )
                        for section in ("require", "require-dev"):
                            for name, version in data.get(
                                section, {}
                            ).items():
                                if name != "php":
                                    deps.append(
                                        {
                                            "name": name,
                                            "required": str(version),
                                            "ecosystem": "php",
                                        }
                                    )
                    elif file_path.name == "Cargo.toml":
                        in_deps = False
                        for line in file_path.read_text(
                            errors="ignore"
                        ).splitlines():
                            stripped = line.strip()
                            if stripped.startswith("["):
                                in_deps = stripped in (
                                    "[dependencies]",
                                    "[dev-dependencies]",
                                )
                            elif (
                                in_deps
                                and "=" in stripped
                                and not stripped.startswith("#")
                            ):
                                name, version = stripped.split("=", 1)
                                deps.append(
                                    {
                                        "name": name.strip(),
                                        "required": version.strip().strip(
                                            '"'
                                        ),
                                        "ecosystem": "rust",
                                    }
                                )
                except Exception as error:
                    outputs.append(
                        (f"Read {file_path.name}", str(error))
                    )

        unique = {}
        for dep in deps:
            name = str(
                dep.get(
                    "name",
                    dep.get("package", dep.get("dependency", "")),
                )
            ).strip()
            if not name:
                continue
            key = (str(dep.get("ecosystem", "")).lower(), name.lower())
            unique[key] = {**dep, "name": name}
        return list(unique.values()), outputs

    @staticmethod
    def _runtime_checks(project_path, project_type):
        checks = []
        p = project_path
        files = {x.name for x in p.iterdir()} if p.is_dir() else set()
        t = str(project_type or "").lower()
        runtimes = []
        if "python" in t or any(
            x in files
            for x in (
                "requirements.txt",
                "pyproject.toml",
                "Pipfile",
                "main.py",
                "app.py",
            )
        ):
            runtimes.append(("Python", "python3", "python3 --version"))
        if (
            "node" in t
            or "javascript" in t
            or "typescript" in t
            or "package.json" in files
        ):
            runtimes.append(("Node.js", "node", "node --version"))
            runtimes.append(("npm", "npm", "npm --version"))
        if "php" in t or "composer.json" in files or "artisan" in files:
            runtimes.append(("PHP", "php", "php --version"))
            if "composer.json" in files:
                runtimes.append(
                    ("Composer", "composer", "composer --version")
                )
        if "java" in t or any(
            x in files
            for x in ("pom.xml", "build.gradle", "build.gradle.kts")
        ):
            runtimes.append(("Java JDK", "java", "java -version"))
            if "pom.xml" in files:
                runtimes.append(("Maven", "mvn", "mvn --version"))
            if (
                "build.gradle" in files
                or "build.gradle.kts" in files
            ):
                runtimes.append(("Gradle", "gradle", "gradle --version"))
        if "go" in t or "go.mod" in files:
            runtimes.append(("Go", "go", "go version"))
        if "rust" in t or "Cargo.toml" in files:
            runtimes.append(("Rust/Cargo", "cargo", "cargo --version"))
        if (
            "dotnet" in t
            or "c#" in t
            or any(n.endswith(".csproj") for n in files)
        ):
            runtimes.append((".NET SDK", "dotnet", "dotnet --info"))
        if (
            "docker" in t
            or "Dockerfile" in files
            or "docker-compose.yml" in files
            or "compose.yaml" in files
        ):
            runtimes.append(("Docker", "docker", "docker --version"))

        seen = set()
        for label, command, version_cmd in runtimes:
            if command in seen:
                continue
            seen.add(command)
            location = shutil.which(command)
            if not location:
                checks.append(
                    {
                        "category": "Runtime",
                        "name": label,
                        "required": command,
                        "status": "MISSING",
                        "details": (
                            f"'{command}' was not found on PATH. "
                            "Install the system runtime/SDK before "
                            "running this project."
                        ),
                    }
                )
            else:
                try:
                    result = subprocess.run(
                        version_cmd,
                        shell=True,
                        cwd=str(p),
                        capture_output=True,
                        text=True,
                        timeout=8,
                    )
                    output = (result.stdout or result.stderr).strip().splitlines()
                    checks.append(
                        {
                            "category": "Runtime",
                            "name": label,
                            "required": command,
                            "status": (
                                "Available"
                                if result.returncode == 0
                                else "Check"
                            ),
                            "details": (
                                output[0] if output else location
                            )[:220],
                        }
                    )
                except Exception as error:
                    checks.append(
                        {
                            "category": "Runtime",
                            "name": label,
                            "required": command,
                            "status": "Check",
                            "details": str(error),
                        }
                    )
        return checks

    # ------------- Analysis flow (with pending action dispatch) -------------
    def analyze_workspace(self):
        project = self.get_selected_workspace_project()
        if not project:
            QMessageBox.information(
                self,
                "Workspace Launcher",
                "Select a registered project first.",
            )
            return
        path = Path(str(project.get("path", ""))).expanduser().resolve()
        if not path.is_dir():
            QMessageBox.warning(
                self,
                "Project Missing",
                f"Project directory does not exist:\n{path}",
            )
            return
        if self.analysis_worker_active:
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

        self.analysis_worker_active = True
        self.analysis_worker = DependencyAnalysisWorker(
            self, project, path
        )
        self.analysis_worker.result_ready.connect(
            self._on_workspace_analysis_complete
        )
        self.analysis_worker.error_occurred.connect(
            self._on_workspace_analysis_error
        )
        self.analysis_worker.finished.connect(
            self._on_analysis_thread_finished
        )
        self.analysis_worker.finished.connect(
            self.analysis_worker.deleteLater
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
            1 for row in rows if row.get("status") == "MISSING"
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

        # Dispatch any action that was waiting for analysis to finish.
        pending = self.pending_workspace_action
        self.pending_workspace_action = None
        if pending == "prepare":
            self.prepare_workspace_environment()
        elif pending == "verify":
            self._run_pip_check_async()
        elif pending == "launch":
            self.launch_workspace_project()

    def _on_workspace_analysis_error(self, message):
        self.workspace_progress.setRange(0, 100)
        self.workspace_progress.setValue(0)
        self.workspace_log_append(f"Analysis failed: {message}")
        self.pending_workspace_action = None
        QMessageBox.warning(
            self, "Dependency Analysis Failed", message
        )

    def _on_analysis_thread_finished(self):
        self.analysis_worker_active = False
        self.analysis_worker = None
        self._on_workspace_worker_finished()

    def _on_workspace_worker_finished(self):
        # Only re-enable Analyze if no other long-running task is active.
        install_running = (
            self.workspace_worker is not None
            and self.workspace_worker.isRunning()
        )
        verify_running = (
            self.verify_worker is not None
            and self.verify_worker.isRunning()
        )
        if not install_running and not verify_running:
            self.analyze_workspace_button.setEnabled(True)

        if (
            self.workspace_progress.maximum() == 0
            and not install_running
            and not verify_running
        ):
            self.workspace_progress.setRange(0, 100)
            self.workspace_progress.setValue(0)

    def _populate_workspace_rows(self, rows):
        self.workspace_dependency_table.setRowCount(len(rows))
        for row_index, data in enumerate(rows):
            values = [
                data.get("category", ""),
                data.get("name", ""),
                data.get("required", ""),
                data.get("status", ""),
                data.get("details", ""),
            ]
            is_missing = data.get("status") == "MISSING"
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setToolTip(str(value or ""))
                if is_missing:
                    item.setForeground(QColor("#ff6b6b"))
                self.workspace_dependency_table.setItem(
                    row_index, col, item
                )
        self.workspace_dependency_table.resizeRowsToContents()

    def _python_dependencies(self):
        deps = []
        for item in self.workspace_dependencies:
            ecosystem = str(item.get("ecosystem", "python")).lower()
            if ecosystem not in ("python", "py", ""):
                continue
            requirement = str(
                item.get("required", item.get("name", ""))
            ).strip()
            name = str(item.get("name", "")).strip()
            if requirement and name:
                if any(
                    op in requirement
                    for op in (
                        "==",
                        ">=",
                        "<=",
                        "~=",
                        "!=",
                        "<",
                        ">",
                        "[",
                    )
                ):
                    deps.append(requirement)
                else:
                    deps.append(name)
        req_file = (
            self.workspace_analysis
            and Path(self.workspace_analysis["path"]) / "requirements.txt"
        )
        if req_file and req_file.is_file():
            try:
                for line in req_file.read_text(errors="ignore").splitlines():
                    line = line.strip()
                    if line and not line.startswith(("#", "-")):
                        deps.append(line)
            except Exception:
                pass
        return list(dict.fromkeys(deps))

    # ------------- Prepare environment -------------
    def prepare_workspace_environment(self):
        project = self.get_selected_workspace_project()

        if not project:
            QMessageBox.information(
                self,
                "Workspace Launcher",
                "Select a registered project first.",
            )
            return

        path = Path(str(project.get("path", ""))).expanduser().resolve()

        if not path.is_dir():
            QMessageBox.warning(
                self,
                "Project Missing",
                f"Project directory does not exist:\n{path}",
            )
            return

        if (
            self.workspace_analysis is None
            or self.workspace_analysis.get("path") != str(path)
        ):
            self.pending_workspace_action = "prepare"
            self.workspace_log_append(
                "Analysis required before preparing environment; "
                "running analysis first."
            )
            self.analyze_workspace()
            return

        # Detect project manifests
        ignored = {
            ".git", ".venv", "venv", "bin", "obj",
            "node_modules", "dist", "build",
        }

        dotnet_projects = []
        for current, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in ignored]

            for filename in files:
                if filename.lower().endswith(
                    (".csproj", ".fsproj", ".vbproj")
                ):
                    dotnet_projects.append(
                        Path(current) / filename
                    )

        solution_files = list(path.glob("*.sln", "*.slnx"))
        is_dotnet_project = bool(dotnet_projects or solution_files)

        # -------------------------------------------------
        # .NET / C# preparation
        # -------------------------------------------------
        if is_dotnet_project:
            dotnet_exe = shutil.which("dotnet")

            message = [
                f"Project: {project.get('name')}",
                f"Path: {path}",
                "",
                "Project type: .NET",
                f".NET project files: {len(dotnet_projects)}",
                f"Solution files: {len(solution_files)}",
                "",
            ]

            if dotnet_exe:
                message.extend([
                    f"Detected dotnet command: {dotnet_exe}",
                    "The project dependencies will be restored using:",
                    "dotnet restore",
                    "",
                    "Then the project will be verified using:",
                    "dotnet build",
                ])
            else:
                message.extend([
                    ".NET SDK: NOT INSTALLED",
                    "",
                    "The installer will attempt to install:",
                    "dotnet-sdk-10.0",
                    "",
                    "Ubuntu authentication may be required.",
                    "After SDK installation, NuGet dependencies "
                    "will be restored and the project will be built.",
                ])

            answer = QMessageBox.question(
                self,
                "Prepare .NET Environment",
                "\n".join(message) + "\n\nContinue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )

            if answer != QMessageBox.Yes:
                self.workspace_log_append(
                    ".NET environment preparation cancelled."
                )
                return

            self._set_workspace_busy(True)
            self.workspace_progress.setRange(0, 100)
            self.workspace_progress.setValue(0)

            self.workspace_log_append(
                "Preparing .NET project environment..."
            )

            self.workspace_worker = WorkspaceTaskWorker(
                self._install_project_dotnet_dependencies,
                str(path),
            )

            self.workspace_worker.log.connect(
                self.workspace_log_append
            )
            self.workspace_worker.progress.connect(
                self._workspace_install_progress
            )
            self.workspace_worker.completed.connect(
                self._workspace_install_completed
            )
            self.workspace_worker.failed.connect(
                self._workspace_task_failed
            )
            self.workspace_worker.finished.connect(
                lambda: self._set_workspace_busy(False)
            )
            self.workspace_worker.finished.connect(
                self.workspace_worker.deleteLater
            )
            self.workspace_worker.start()
            return

        # -------------------------------------------------
        # Existing Python preparation
        # -------------------------------------------------
        python_deps = self._python_dependencies()

        if not python_deps and not (
            (path / "requirements.txt").is_file()
            or (path / "pyproject.toml").is_file()
            or (path / "Pipfile").is_file()
        ):
            QMessageBox.information(
                self,
                "No Python Dependencies",
                "No Python package requirements were detected.",
            )
            return

        env_path = path / ".venv"

        message = [
            f"Project: {project.get('name')}",
            f"Path: {path}",
            f"Python packages to install: {len(python_deps)}",
            "",
            "A virtual environment will be created/reused at:",
            str(env_path),
            "",
            "No system-wide pip installation will be performed.",
        ]

        if python_deps:
            message.extend([
                "",
                "Package requirements:",
                *[f"• {item}" for item in python_deps[:30]],
            ])

            if len(python_deps) > 30:
                message.append(
                    f"…and {len(python_deps) - 30} more"
                )

        answer = QMessageBox.question(
            self,
            "Confirm Project-local Installation",
            "\n".join(message) + "\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            self.workspace_log_append(
                "Installation cancelled by user."
            )
            return

        self._set_workspace_busy(True)
        self.workspace_progress.setRange(0, 100)
        self.workspace_progress.setValue(0)

        self.workspace_log_append(
            "Preparing project-local Python environment..."
        )

        self.workspace_worker = WorkspaceTaskWorker(
            self._install_project_python_dependencies,
            str(path),
            python_deps,
        )

        self.workspace_worker.log.connect(
            self.workspace_log_append
        )
        self.workspace_worker.progress.connect(
            self._workspace_install_progress
        )
        self.workspace_worker.completed.connect(
            self._workspace_install_completed
        )
        self.workspace_worker.failed.connect(
            self._workspace_task_failed
        )
        self.workspace_worker.finished.connect(
            lambda: self._set_workspace_busy(False)
        )
        self.workspace_worker.finished.connect(
            self.workspace_worker.deleteLater
        )
        self.workspace_worker.start()

    # ------------- Install (static, runs in worker thread) -------------
    @staticmethod
    def _install_project_dotnet_dependencies(
        project_path,
        log_callback=None,
        progress_callback=None,
    ):
        path = Path(project_path).expanduser().resolve()

        if not path.is_dir():
            raise RuntimeError(
                f"Project directory does not exist: {path}"
            )

        def log(message):
            if log_callback:
                log_callback(str(message))

        def progress(value, message=""):
            if progress_callback:
                progress_callback(int(value), str(message))

        ignored = {
            ".git", ".venv", "venv", "node_modules",
            "bin", "obj", "dist", "build",
        }

        project_files = []
        solution_files = list(path.glob("*.sln"))

        for current, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in ignored]

            for filename in files:
                if filename.lower().endswith(
                    (".csproj", ".fsproj", ".vbproj")
                ):
                    project_files.append(
                        Path(current) / filename
                    )

        # Select .NET build targets

        if len(solution_files) > 1:
            raise RuntimeError(
                "Multiple solution files found. "
                "Please select a solution."
            )

        if solution_files:
            targets = solution_files
            log(f"Selected solution: {targets[0].name}")

        elif project_files:
            targets = project_files

            log(f"Detected {len(targets)} .NET project file(s).")

            for project_file in targets:
                log(f"  - {project_file.name}")

        else:
            raise RuntimeError(
                "No .NET solution or project file found."
        )

        def run_command(command, timeout=1800):
            log("$ " + " ".join(str(x) for x in command))

            process = subprocess.Popen(
                command,
                cwd=str(path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            output_lines = []

            try:
                for line in process.stdout:
                    line = line.rstrip()
                    output_lines.append(line)
                    log(line)

                return_code = process.wait(timeout=timeout)

            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise RuntimeError(
                    "Command timed out:\n"
                    + " ".join(str(x) for x in command)
                )

            output = "\n".join(output_lines)

            if return_code != 0:
                raise RuntimeError(
                    "Command failed:\n"
                    + " ".join(str(x) for x in command)
                    + "\n\n"
                    + output[-8000:]
                )

            return output

        # Step 1: Check .NET SDK
        progress(5, "Checking .NET SDK")
        dotnet = shutil.which("dotnet")

        if not dotnet:
            log(".NET SDK not found.")
            log("Checking Ubuntu package availability...")

            apt_cache = shutil.which("apt-cache")
            pkexec = shutil.which("pkexec")

            if not apt_cache or not pkexec:
                raise RuntimeError(
                    ".NET SDK is missing, and apt-cache/pkexec "
                    "is unavailable.\n"
                    "Install .NET 10 SDK manually using the official "
                    "Ubuntu instructions."
                )
            log("Updating APT package information...")
            progress(8, "Updating package information")

            run_command(
                [pkexec, "apt-get", "update"],
                timeout=1800,
            )

            policy = subprocess.run(
                [apt_cache, "policy", "dotnet-sdk-10.0"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if "Candidate: (none)" in policy.stdout or not policy.stdout.strip():
                raise RuntimeError(
                    "dotnet-sdk-10.0 is not available in the currently "
                    "configured APT repositories.\n\n"
                    "Your Ubuntu version may require a different "
                    "package feed.\n"
                    "Please configure the official .NET repository "
                    "for your Ubuntu release, then try again.\n\n"
                    "Official guide:\n"
                    "https://learn.microsoft.com/dotnet/core/install/"
                    "linux-ubuntu-install"
                )

            log("Installing .NET 10 SDK through Ubuntu package manager.")
            log("Ubuntu authentication may appear.")

            progress(10, "Installing .NET 10 SDK")

            run_command(
                [
                    pkexec,
                    "apt-get",
                    "install",
                    "-y",
                    "dotnet-sdk-10.0",
                ],
                timeout=3600,
            )

            dotnet = shutil.which("dotnet")

            if not dotnet:
                raise RuntimeError(
                    ".NET SDK installation command completed, "
                    "but the dotnet command was not found.\n"
                    "Restart the application and try again."
                )

        # Step 2: Verify SDK
        progress(25, "Verifying .NET SDK")

        sdk_result = subprocess.run(
            [dotnet, "--list-sdks"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=30,
        )

        if sdk_result.returncode != 0:
            raise RuntimeError(
                "Unable to verify .NET SDK:\n"
                + sdk_result.stderr
            )

        sdk_output = sdk_result.stdout.strip()
        log("Installed SDKs:")
        log(sdk_output or "(No SDK listed)")

        if not re.search(r"(?m)^10\.", sdk_output):
            raise RuntimeError(
                "The project requires .NET 10, but the .NET 10 SDK "
                "was not detected.\n\n"
                "Detected SDKs:\n"
                + (sdk_output or "None")
            )

        # Step 3: Restore NuGet dependencies
        restore_outputs = []
        build_outputs = []

        total = len(targets)

        for index, target in enumerate(targets, start=1):

            log(
                f"[{index}/{total}] Restoring: {target.name}"
            )

            progress(
                40 + int((index / total) * 25),
                f"Restoring {target.name}",
            )

            output = run_command(
                [
                    dotnet,
                    "restore",
                    str(target),
                ],
                timeout=3600,
            )

            restore_outputs.append(output)

        # Step 4: Build projects
        for index, target in enumerate(targets, start=1):

            log(
                f"[{index}/{total}] Building: {target.name}"
            )

            progress(
                65 + int((index / total) * 30),
                f"Building {target.name}",
            )

            output = run_command(
                [
                    dotnet,
                    "build",
                    str(target),
                    "--no-restore",
                ],
                timeout=3600,
            )

            build_outputs.append(output)

        restore_output = "\n".join(restore_outputs)
        build_output = "\n".join(build_outputs)

        # Step 5: Result
        progress(100, "Done")

        log(".NET dependency restoration completed.")
        log(".NET build verification completed successfully.")

        return {
            "path": str(path),
            "target": [str(item) for item in targets],
            "ecosystem": "dotnet",
            "sdk": sdk_output,
            "restore_output": restore_output,
            "build_output": build_output,
            "verification_ok": True,
            "verification": (
                "All .NET projects restored and built successfully."
            ),
        }

    @staticmethod
    def _stream_subprocess(command, cwd, log, progress, timeout=1800):
        """Run a subprocess streaming stdout/stderr with a real timeout.

        The previous implementation used ``process.stdout.read(1)`` which blocks
        forever if the child produces no output, so ``process.wait(timeout=...)``
        was never reached. Here a watchdog thread kills the process when the
        deadline expires.
        """
        log("=" * 45)
        log("Running: " + " ".join(command))
        log("=" * 45)

        output_lines = []
        current_package = "dependencies"
        buffer = ""
        timed_out = threading.Event()

        progress_pattern = re.compile(
            r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*(kB|KB|MB|GB)",
            re.IGNORECASE,
        )
        package_pattern = re.compile(
            r"(?:Downloading|Collecting|Processing)\s+([A-Za-z0-9_.\-]+)",
            re.IGNORECASE,
        )

        def process_line(line):
            nonlocal current_package
            line = line.strip()
            if not line:
                return
            # Strip ANSI colour sequences.
            line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line)

            package_match = package_pattern.search(line)
            if package_match:
                current_package = package_match.group(1)
                progress(0, current_package)

            progress_match = progress_pattern.search(line)
            if progress_match:
                downloaded = float(progress_match.group(1))
                total = float(progress_match.group(2))
                if total > 0:
                    percentage = min(100, int((downloaded / total) * 100))
                    progress(percentage, current_package)

            output_lines.append(line)
            log(line)

        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        # --- Watchdog: kill the process if it exceeds the deadline. ----------
        def watchdog():
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out.set()
                try:
                    process.kill()
                except Exception:
                    pass

        watchdog_thread = threading.Thread(target=watchdog, daemon=True)
        watchdog_thread.start()

        try:
            # Read char-by-char so we can handle '\r' progress updates pip emits.
            while True:
                char = process.stdout.read(1)
                if char == "":
                    break
                if char in ("\r", "\n"):
                    if buffer:
                        process_line(buffer)
                        buffer = ""
                else:
                    buffer += char
            if buffer:
                process_line(buffer)

            return_code = process.wait()
        except Exception:
            try:
                process.kill()
                process.wait()
            except Exception:
                pass
            raise
        finally:
            try:
                process.stdout.close()
            except Exception:
                pass

        output = "\n".join(output_lines)

        if timed_out.is_set():
            raise RuntimeError(
                f"pip install timed out after {timeout} seconds.\n"
                f"Last output:\n{output[-5000:]}"
            )

        if return_code != 0:
            raise RuntimeError(
                f"pip install failed (exit code {return_code}):\n{output[-5000:]}"
            )

        return output

    # ------------- Completion / failure handlers -------------
    def _workspace_install_completed(self, _message, result):
        self.workspace_progress.setRange(0, 100)
        self.workspace_progress.setValue(100)

        if not isinstance(result, dict):
            self.workspace_log_append(
                "Installation returned no result object."
            )
            self._set_workspace_busy(False)
            return

        ecosystem = result.get("ecosystem", "python")

        self.workspace_log_append(
            f"Environment ready: {result.get('path')}"
        )

        if ecosystem == "dotnet":
            if result.get("verification_ok"):
                self.workspace_log_append(
                    ".NET verification passed: restore and build OK."
                )

                QMessageBox.information(
                    self,
                    ".NET Environment Prepared",
                    "The .NET environment is ready.\n\n"
                    "NuGet dependencies restored successfully "
                    "and the project build passed.\n\n"
                    "Refreshing dependency analysis.",
                )
            else:
                self.workspace_log_append(
                    ".NET verification reported issues:\n"
                    + (result.get("verification") or "(no details)")
                )

                QMessageBox.warning(
                    self,
                    ".NET Verification Warning",
                    "The .NET environment was prepared, but "
                    "verification reported issues. "
                    "Review Workspace Activity.",
                )

        else:
            if result.get("verification_ok"):
                self.workspace_log_append(
                    "Dependency verification passed: pip check OK."
                )

                QMessageBox.information(
                    self,
                    "Environment Prepared",
                    "Project-local Python environment is ready "
                    "and dependency verification passed.\n\n"
                    "Refreshing dependency analysis.",
                )
            else:
                self.workspace_log_append(
                    "Dependency verification reported issues:\n"
                    + (result.get("verification") or "(no details)")
                )

                QMessageBox.warning(
                    self,
                    "Verification Warning",
                    "Environment was prepared, but pip check "
                    "reported dependency issues. "
                    "Review Workspace Activity.",
                )

        self.workspace_log_append(
            "Refreshing dependency table..."
        )
        self.analyze_workspace()

    def _workspace_task_failed(self, error):
        self.workspace_progress.setRange(0, 100)
        self.workspace_progress.setValue(0)

        self.workspace_log_append(
            "Operation failed: " + str(error)
        )

        QMessageBox.critical(
            self,
            "Workspace Operation Failed",
            str(error),
        )

        self._set_workspace_busy(False)

    # ------------- Verify -------------
    def verify_workspace_environment(self):
        project = self.get_selected_workspace_project()
        if not project:
            QMessageBox.information(
                self, "Workspace Launcher",
                "Select a registered project first.",
            )
            return
        path = Path(str(project.get("path", ""))).expanduser().resolve()

        if (
            self.workspace_analysis is None
            or self.workspace_analysis.get("path") != str(path)
        ):
            self.pending_workspace_action = "verify"
            self.workspace_log_append(
                "Analysis required before verifying; running analysis first."
            )
            self.analyze_workspace()
            return

        self._run_pip_check_async()

    def _run_pip_check_async(self):
        project = self.get_selected_workspace_project()
        if not project:
            return
        path = Path(str(project.get("path", ""))).expanduser().resolve()
        env_python = path / ".venv" / "bin" / "python"

        if not env_python.is_file():
            self.workspace_log_append(
                "No project-local .venv found. Use Prepare / Install "
                "Missing Dependencies if this project needs Python packages."
            )
            QMessageBox.information(
                self,
                "Environment Not Found",
                "No project-local .venv exists yet. Analyze the runtime "
                "checks, then prepare the environment if needed.",
            )
            return

        if self.verify_worker and self.verify_worker.isRunning():
            return

        self._set_workspace_busy(True)
        self.workspace_log_append("Running pip check…")

        self.verify_worker = VerifyEnvironmentWorker(env_python, path)
        self.verify_worker.completed.connect(
            self._on_verify_completed
        )
        self.verify_worker.finished.connect(
            lambda: self._set_workspace_busy(False)
        )
        self.verify_worker.finished.connect(
            self.verify_worker.deleteLater
        )
        self.verify_worker.start()

    def _on_verify_completed(self, ok, detail):
        if ok:
            self.workspace_log_append(
                "VERIFIED: pip check passed in project .venv."
            )
            QMessageBox.information(
                self,
                "Verification Passed",
                "Project-local Python environment exists and pip check passed.",
            )
        else:
            self.workspace_log_append(
                "VERIFICATION ISSUES:\n" + (detail or "(no details)")
            )
            QMessageBox.warning(
                self,
                "Verification Issues",
                detail or "pip check found dependency issues.",
            )

    # ------------- Launch -------------
    def launch_workspace_project(self):
        project = self.get_selected_workspace_project()
        if not project:
            QMessageBox.information(
                self, "Workspace Launcher",
                "Select a registered project first.",
            )
            return
        path = Path(str(project.get("path", ""))).expanduser().resolve()
        if not path.is_dir():
            QMessageBox.warning(
                self, "Project Missing",
                f"Project directory does not exist:\n{path}",
            )
            return

        if (
            self.workspace_analysis is None
            or self.workspace_analysis.get("path") != str(path)
        ):
            self.pending_workspace_action = "launch"
            self.workspace_log_append(
                "Analysis required before launching; running analysis first."
            )
            self.analyze_workspace()
            return

        missing = []
        for row in range(self.workspace_dependency_table.rowCount()):
            cat = self.workspace_dependency_table.item(row, 0)
            status = self.workspace_dependency_table.item(row, 3)
            name = self.workspace_dependency_table.item(row, 1)
            if (
                cat
                and status
                and name
                and cat.text() == "Runtime"
                and status.text() == "MISSING"
            ):
                missing.append(name.text())

        if missing:
            answer = QMessageBox.question(
                self,
                "Runtime Missing",
                "These runtimes were not found:\n"
                + "\n".join(f"• {x}" for x in missing)
                + "\n\nTry launching anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        try:
            from plugins.workspace_launcher.runner import ProjectRunner
        except Exception:
            ProjectRunner = None  # type: ignore

        if ProjectRunner is not None:
            answer = QMessageBox.question(
                self,
                "Launch Project",
                f"Launch '{project.get('name')}'?\n\n{path}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            try:
                runner = ProjectRunner()
                result = self._call_compatible(runner.launch, project)
                self.workspace_log_append(
                    f"Launch request sent to ProjectRunner. Result: {result}"
                )
                QMessageBox.information(
                    self,
                    "Launch Requested",
                    f"ProjectRunner launch request completed.\n\n"
                    f"{result if result is not None else 'Check the project terminal/process for output.'}",
                )
                return
            except Exception as error:
                self.workspace_log_append(
                    f"ProjectRunner failed: {error}"
                )
                QMessageBox.warning(
                    self,
                    "Runner Failed",
                    f"ProjectRunner could not launch the project:\n{error}\n\n"
                    "You can try a detected entry point manually from the project folder.",
                )
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
                    candidates.append(
                        [
                            str(env_python),
                            str(path / "backend" / name),
                        ]
                    )
        if (path / "package.json").is_file() and shutil.which("npm"):
            candidates.append(["npm", "run", "dev"])
        if (path / "run.sh").is_file():
            candidates.append(["bash", str(path / "run.sh")])
        if (path / "run.bat").is_file():
            QMessageBox.information(
                self,
                "Windows Script Detected",
                "This project contains run.bat, which is a Windows batch "
                "file and cannot run directly on Ubuntu. Use a Linux "
                "run.sh or configure the project runner.",
            )
            return
        if not candidates:
            QMessageBox.warning(
                self,
                "No Launch Entry Point",
                "No safe default entry point was detected. "
                "Add/configure the project runner for this project type.",
            )
            return
        labels = [" ".join(command) for command in candidates]
        selected, ok = QInputDialog.getItem(
            self,
            "Choose Launch Command",
            "Detected launch options:",
            labels,
            0,
            False,
        )
        if not ok or not selected:
            return
        command = candidates[labels.index(selected)]
        try:
            subprocess.Popen(
                command,
                cwd=str(path),
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            QMessageBox.information(
                self,
                "Launch Started",
                f"Started:\n{' '.join(command)}\n\nWorking directory:\n{path}",
            )
            self.workspace_log_append(
                f"Started process: {' '.join(command)}"
            )
        except Exception as error:
            QMessageBox.critical(self, "Launch Failed", str(error))

    def _set_workspace_busy(self, busy):
        for button in (
            self.analyze_workspace_button,
            self.prepare_environment_button,
            self.verify_workspace_button,
            self.launch_workspace_button,
            self.refresh_workspace_button,
        ):
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

        self.port_table = self.make_table(
            ["Port", "Address", "Protocol", "PID", "Process", "Status"]
        )
        self.port_table.itemSelectionChanged.connect(
            self.show_selected_process
        )
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
            QMessageBox.warning(
                self, "Port Manager", f"Could not load ports:\n{error}"
            )
            return
        self.port_table.setRowCount(len(ports))
        for row, port in enumerate(ports):
            values = [
                str(port.get("port", "")),
                str(port.get("address", "")),
                str(port.get("protocol", "")),
                str(
                    port.get("pid")
                    if port.get("pid") is not None
                    else "-"
                ),
                str(port.get("process", "")),
                str(port.get("status", "")),
            ]
            for col, value in enumerate(values):
                self.port_table.setItem(
                    row, col, QTableWidgetItem(value)
                )
        self.process_info.setText("No process selected.")

    def search_port(self):
        text = self.port_search_field.text().strip()
        if not text:
            return
        if not text.isdigit():
            QMessageBox.information(
                self, "Search Port", "Enter a valid numeric port number."
            )
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
        QMessageBox.information(
            self,
            "Search Port",
            f"Port {port_number} was not found in the current list.",
        )

    def show_selected_process(self):
        selected = self.port_table.selectionModel().selectedRows()
        if not selected:
            self.process_info.setText("No process selected.")
            return
        row = selected[0].row()
        pid_item = self.port_table.item(row, 3)
        if not pid_item or pid_item.text() == "-":
            self.process_info.setText(
                "No process information available."
            )
            return
        try:
            details = self.port_manager.get_process_details(
                int(pid_item.text())
            )
        except Exception as error:
            self.process_info.setText(
                f"Could not read process details: {error}"
            )
            return
        if details:
            self.process_info.setText(
                f"PID: {details.get('pid')}   |   "
                f"Process: {details.get('name')}   |   "
                f"Status: {details.get('status')}   |   "
                f"User: {details.get('username')}"
            )

    def show_process_details(self):
        selected = self.port_table.selectionModel().selectedRows()
        if not selected:
            QMessageBox.information(
                self, "Process Details", "Select a process first."
            )
            return
        row = selected[0].row()
        pid_item = self.port_table.item(row, 3)
        if not pid_item or pid_item.text() == "-":
            QMessageBox.information(
                self,
                "Process Details",
                "No PID is available for this port.",
            )
            return
        try:
            details = self.port_manager.get_process_details(
                int(pid_item.text())
            )
        except Exception as error:
            QMessageBox.warning(self, "Process Details", str(error))
            return
        if not details:
            QMessageBox.information(
                self,
                "Process Details",
                "Process details are unavailable.",
            )
            return
        message = "\n".join(
            f"{key.replace('_', ' ').title()}: {value}"
            for key, value in details.items()
        )
        QMessageBox.information(self, "Process Details", message)

    def kill_selected_process(self):
        selected = self.port_table.selectionModel().selectedRows()
        if not selected:
            QMessageBox.information(
                self, "Kill Process", "Select a process first."
            )
            return
        row = selected[0].row()
        port_item = self.port_table.item(row, 0)
        pid_item = self.port_table.item(row, 3)
        process_item = self.port_table.item(row, 4)
        if (
            not port_item
            or not pid_item
            or not process_item
            or pid_item.text() == "-"
        ):
            QMessageBox.information(
                self,
                "Kill Process",
                "A valid PID is not available for the selected port.",
            )
            return
        port = int(port_item.text())
        pid = int(pid_item.text())
        name = process_item.text()
        answer = QMessageBox.question(
            self,
            "Confirm Process Termination",
            f"Terminate '{name}' (PID {pid})?\n\nPort: {port}\n"
            "This may stop an application using this port.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
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
            QMessageBox.warning(
                self,
                "Termination Failed",
                f"Could not terminate process {pid}. It may require "
                "elevated permissions or may have already exited.",
            )

    # ==================================================
    # Project Cache Cleaner
    # ==================================================
    def create_cache_cleaner_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(35, 30, 35, 30)
        layout.setSpacing(15)

        title = QLabel("Project Cache Cleaner")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Scan a project directory and safely remove regenerable "
            "cache, build artefacts, and temporary files."
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        # --- Project selection ---
        select_group = QGroupBox("Project")
        select_layout = QVBoxLayout(select_group)
        top = QHBoxLayout()
        self.cache_project_combo = QComboBox()
        self.cache_project_combo.currentIndexChanged.connect(
            self.on_cache_project_changed
        )
        refresh_button = QPushButton("Refresh Projects")
        refresh_button.clicked.connect(self.load_cache_projects)
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self.browse_cache_project)
        top.addWidget(self.cache_project_combo, 1)
        top.addWidget(refresh_button)
        top.addWidget(browse_button)
        select_layout.addLayout(top)

        self.cache_path_label = QLabel("Select a project to scan.")
        self.cache_path_label.setWordWrap(True)
        self.cache_path_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        select_layout.addWidget(self.cache_path_label)
        layout.addWidget(select_group)

        # --- Action buttons ---
        action_row = QHBoxLayout()
        self.cache_scan_button = QPushButton("Scan Cache")
        self.cache_scan_button.clicked.connect(self.scan_cache_project)
        self.cache_select_all_button = QPushButton("Select All")
        self.cache_select_all_button.clicked.connect(
            self.cache_select_all
        )
        self.cache_deselect_all_button = QPushButton("Deselect All")
        self.cache_deselect_all_button.clicked.connect(
            self.cache_deselect_all
        )
        self.cache_clean_button = QPushButton("Clean Selected")
        self.cache_clean_button.setObjectName("DangerButton")
        self.cache_clean_button.clicked.connect(self.clean_cache_selected)
        action_row.addWidget(self.cache_scan_button)
        action_row.addWidget(self.cache_select_all_button)
        action_row.addWidget(self.cache_deselect_all_button)
        action_row.addStretch()
        action_row.addWidget(self.cache_clean_button)
        layout.addLayout(action_row)

        # --- Results table (checkable) ---
        self.cache_table = QTableWidget()
        self.cache_table.setColumnCount(4)
        self.cache_table.setHorizontalHeaderLabels(
            ["Select", "Path", "Type", "Size"]
        )
        self.cache_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cache_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.cache_table.verticalHeader().setVisible(False)
        self.cache_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self.cache_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self.cache_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        self.cache_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents
        )
        layout.addWidget(self.cache_table, 1)

        # --- Status ---
        self.cache_status = QLabel("Status: idle.")
        self.cache_status.setObjectName("ProcessInfo")
        layout.addWidget(self.cache_status)

        return page

    def load_cache_projects(self):
        if not hasattr(self, "cache_project_combo"):
            return
        current_id = self.cache_project_combo.currentData()
        self.cache_project_combo.blockSignals(True)
        self.cache_project_combo.clear()
        try:
            projects = self.project_registry.get_projects() or []
        except Exception:
            projects = []
        for project in projects:
            name = project.get("name", "Unnamed")
            path = project.get("path", "")
            label = f"{name}  —  {path}"
            self.cache_project_combo.addItem(label, project.get("path"))
        if current_id is not None:
            for i in range(self.cache_project_combo.count()):
                if self.cache_project_combo.itemData(i) == current_id:
                    self.cache_project_combo.setCurrentIndex(i)
                    break
        self.cache_project_combo.blockSignals(False)
        self.on_cache_project_changed()

    def browse_cache_project(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Project Folder", str(Path.home())
        )
        if not folder:
            return
        path = str(Path(folder).resolve())
        # Add or select a custom entry
        for i in range(self.cache_project_combo.count()):
            if self.cache_project_combo.itemData(i) == path:
                self.cache_project_combo.setCurrentIndex(i)
                self.on_cache_project_changed()
                return
        self.cache_project_combo.blockSignals(True)
        self.cache_project_combo.addItem(f"(Custom) {path}", path)
        self.cache_project_combo.setCurrentIndex(
            self.cache_project_combo.count() - 1
        )
        self.cache_project_combo.blockSignals(False)
        self.on_cache_project_changed()

    def on_cache_project_changed(self, *_):
        if not hasattr(self, "cache_path_label"):
            return
        path = self.cache_project_combo.currentData()
        self.cache_project_path = path
        if not path:
            self.cache_path_label.setText("Select a project to scan.")
            self.cache_table.setRowCount(0)
            return
        p = Path(str(path)).expanduser()
        self.cache_path_label.setText(f"Path: {p}")
        self.cache_table.setRowCount(0)
        self.cache_status.setText("Status: ready. Click 'Scan Cache'.")

    def scan_cache_project(self):

        if not self.cache_project_path:
            QMessageBox.information(
                self,
                "Project Cache Cleaner",
                "Select a project folder first.",
            )
            return

        path = Path(str(self.cache_project_path)).expanduser()

        if not path.is_dir():
            QMessageBox.warning(
                self,
                "Project Missing",
                f"Directory does not exist:\n{path}",
            )
            return

        # Prevent multiple simultaneous scans
        if self.cache_scan_worker is not None:
            if self.cache_scan_worker.isRunning():
                return

        self.cache_scan_button.setEnabled(False)
        self.cache_status.setText("Status: scanning...")
        self.cache_table.setRowCount(0)

        self.cache_scan_worker = CacheScanWorker(
            self.cache_cleaner,
            str(path)
        )

        self.cache_scan_worker.completed.connect(
            self._on_cache_scan_completed
        )

        self.cache_scan_worker.failed.connect(
            self._on_cache_scan_failed
        )

        # Reset worker reference after completion
        self.cache_scan_worker.finished.connect(
            self._on_cache_scan_worker_finished
        )

        # Delete the finished worker
        self.cache_scan_worker.finished.connect(
            self.cache_scan_worker.deleteLater
        )

        self.cache_scan_worker.start()
    
    def _on_cache_scan_worker_finished(self):
        self.cache_scan_worker = None
        self.cache_scan_button.setEnabled(True)

    def _on_cache_scan_completed(self, results):
        self.cache_scan_results = results or []
        self.cache_table.setRowCount(len(self.cache_scan_results))
        total_size = 0
        for row, entry in enumerate(self.cache_scan_results):
            size = int(entry.get("size", 0))
            total_size += size

            check_item = QTableWidgetItem()
            check_item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            check_item.setCheckState(Qt.CheckState.Unchecked)
            self.cache_table.setItem(row, 0, check_item)

            path_item = QTableWidgetItem(str(entry.get("path", "")))
            path_item.setToolTip(str(entry.get("path", "")))
            self.cache_table.setItem(row, 1, path_item)

            type_item = QTableWidgetItem(str(entry.get("type", "Unknown")))
            self.cache_table.setItem(row, 2, type_item)

            size_item = QTableWidgetItem(
                self.cache_cleaner.format_size(size)
            )
            size_item.setData(Qt.ItemDataRole.UserRole, size)
            self.cache_table.setItem(row, 3, size_item)

        if self.cache_scan_results:
            self.cache_status.setText(
                f"Status: {len(self.cache_scan_results)} item(s) found, "
                f"total {self.cache_cleaner.format_size(total_size)}."
            )
        else:
            self.cache_status.setText(
                "Status: scan completed, no cache items found."
            )

    def _on_cache_scan_failed(self, message):
        self.cache_status.setText("Status: scan failed.")
        QMessageBox.warning(
            self, "Cache Scan Failed", message
        )

    def cache_select_all(self):
        for row in range(self.cache_table.rowCount()):
            item = self.cache_table.item(row, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked)

    def cache_deselect_all(self):
        for row in range(self.cache_table.rowCount()):
            item = self.cache_table.item(row, 0)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)

    def clean_cache_selected(self):
        if not self.cache_project_path:
            QMessageBox.information(
                self,
                "Project Cache Cleaner",
                "Select a project folder first.",
            )
            return
        selected_paths = []
        total_size = 0
        for row in range(self.cache_table.rowCount()):
            check_item = self.cache_table.item(row, 0)
            path_item = self.cache_table.item(row, 1)
            size_item = self.cache_table.item(row, 3)
            if (
                check_item
                and path_item
                and check_item.checkState() == Qt.CheckState.Checked
            ):
                selected_paths.append(path_item.text())
                if size_item:
                    total_size += int(
                        size_item.data(Qt.ItemDataRole.UserRole) or 0
                    )

        if not selected_paths:
            QMessageBox.information(
                self,
                "Project Cache Cleaner",
                "No items selected for cleanup.",
            )
            return

        answer = QMessageBox.question(
            self,
            "Confirm Cache Cleanup",
            f"Delete {len(selected_paths)} item(s)?\n"
            f"Approximate storage to reclaim: "
            f"{self.cache_cleaner.format_size(total_size)}\n\n"
            "Only regenerable cache/build items should be selected. "
            "This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.cache_clean_button.setEnabled(False)
        try:
            result = self.cache_cleaner.clean_selected(
                self.cache_project_path,
                selected_paths,
            )
            successful = sum(
                1 for item in result
                if item.get("success")
            )
            failed = len(result) - successful
            freed_size = sum(
                item.get("freed_size", 0)
                for item in result
                if item.get("success")
            )

            self.scan_cache_project()

            message = (
                f"Cleanup completed.\n\n"
                f"Successfully cleaned: {successful}\n"
                f"Failed: {failed}\n"
                f"Storage reclaimed: "
                f"{self.cache_cleaner.format_size(freed_size)}"
            )
            QMessageBox.information(
                self,
                "Cleanup Result",
                message,
            )
            self.cache_status.setText(
                "Status: Cleanup completed. "
                f"{self.cache_cleaner.format_size(freed_size)} reclaimed."
            )
        except Exception as error:
            QMessageBox.warning(
                self,
                "Cleanup Failed",
                str(error),
            )
        finally:
            self.cache_clean_button.setEnabled(True)

    # -------------------- Styling --------------------
    def get_stylesheet(self):
        return """
        /* =========================================
        UBUNTU DEVTOOLS
        MODERN DEVELOPER WORKSTATION THEME
        ========================================= */

        /* ---------- GLOBAL ---------- */

        QMainWindow {
            background-color: #10141D;
            color: #E6EDF7;
        }

        QWidget {
            color: #DCE5F1;
            font-family: "Ubuntu", "Segoe UI", sans-serif;
            font-size: 13px;
        }

        QLabel {
            background-color: transparent;
            color: #DCE5F1;
        }

        /* ---------- MAIN CONTAINERS ---------- */

        QStackedWidget {
            background-color: #111722;
            border: none;
        }

        QFrame {
            background-color: #171F2C;
            border: none;
        }

        QScrollArea {
            background-color: #111722;
            border: none;
        }

        QScrollArea > QWidget > QWidget {
            background-color: #111722;
        }

        /* ---------- SIDEBAR ---------- */

        #Sidebar {
            background-color: #0C111A;
            border-right: 1px solid #273244;
        }

        #Logo {
            background-color: transparent;
            color: #F4F7FC;
            font-size: 21px;
            font-weight: 800;
        }

        #SidebarSubtitle {
            background-color: transparent;
            color: #78889F;
            font-size: 11px;
        }

        /* ---------- NAVIGATION ---------- */

        #Navigation {
            background-color: #0C111A;
            border: none;
            color: #94A3B8;
            font-size: 13px;
            outline: none;
        }

        #Navigation::item {
            background-color: #0C111A;
            color: #94A3B8;
            padding: 12px 14px;
            margin: 3px 7px;
            border-radius: 7px;
            border: none;
        }

        #Navigation::item:hover {
            background-color: #1B293B;
            color: #F1F5F9;
        }

        #Navigation::item:selected {
            background-color: #163448;
            color: #43D9F5;
            font-weight: bold;
            border-left: 3px solid #43D9F5;
        }

        /* ---------- PAGE HEADER ---------- */

        #PageTitle {
            background-color: transparent;
            color: #F1F5F9;
            font-size: 25px;
            font-weight: 800;
        }

        #PageSubtitle {
            background-color: transparent;
            color: #8493A8;
            font-size: 12px;
        }

        #SectionTitle {
            background-color: transparent;
            color: #E8EEF8;
            font-size: 15px;
            font-weight: bold;
        }

        /* ---------- DASHBOARD CARDS ---------- */

        #StatCard {
            background-color: #192333;
            border: 1px solid #2B3A50;
            border-radius: 10px;
        }

        #ScanCard {
            background-color: #192333;
            border: 1px solid #2B3A50;
            border-radius: 10px;
        }

        #InfoCard {
            background-color: #192333;
            border: 1px solid #2B3A50;
            border-radius: 10px;
        }

        #StatCard:hover,
        #ScanCard:hover,
        #InfoCard:hover {
            background-color: #202E42;
            border: 1px solid #3D6680;
        }

        #StatTitle {
            background-color: transparent;
            color: #91A3BA;
            font-size: 11px;
            font-weight: 600;
        }

        #StatValue {
            background-color: transparent;
            color: #F1F6FC;
            font-size: 25px;
            font-weight: 800;
        }

        /* ---------- BUTTONS ---------- */

        QPushButton {
            background-color: #13A8C7;
            color: #07151D;
            border: 1px solid #13A8C7;
            border-radius: 7px;
            padding: 9px 15px;
            font-size: 12px;
            font-weight: bold;
        }

        QPushButton:hover {
            background-color: #39C9E5;
            border-color: #39C9E5;
            color: #07151D;
        }

        QPushButton:pressed {
            background-color: #087F9B;
            border-color: #087F9B;
        }

        QPushButton:disabled {
            background-color: #293445;
            color: #718096;
            border: 1px solid #293445;
        }

        /* Secondary Button */

        #SecondaryButton {
            background-color: #202C3D;
            color: #C7D5E8;
            border: 1px solid #3A4B62;
        }

        #SecondaryButton:hover {
            background-color: #2B3D54;
            color: #FFFFFF;
            border-color: #43D9F5;
        }

        /* Danger Button */

        #DangerButton {
            background-color: #39212A;
            color: #FF8798;
            border: 1px solid #713747;
        }

        #DangerButton:hover {
            background-color: #512735;
            color: #FFFFFF;
            border-color: #E65B73;
        }

        /* ---------- INPUT FIELDS ---------- */

        QLineEdit,
        QComboBox {
            background-color: #192333;
            color: #E6EDF7;
            border: 1px solid #35445A;
            border-radius: 7px;
            padding: 9px 11px;
            selection-background-color: #12647C;
            selection-color: #FFFFFF;
        }

        QLineEdit:hover,
        QComboBox:hover {
            border-color: #60758F;
        }

        QLineEdit:focus,
        QComboBox:focus {
            background-color: #1C2B40;
            border: 1px solid #43D9F5;
        }

        QLineEdit::placeholder {
            color: #718096;
        }

        QComboBox::drop-down {
            background-color: #192333;
            border: none;
            width: 25px;
        }

        QComboBox QAbstractItemView {
            background-color: #192333;
            color: #DCE5F1;
            border: 1px solid #35445A;
            selection-background-color: #16465D;
            selection-color: #43D9F5;
            padding: 5px;
        }

        /* ---------- TABLES ---------- */

        QTableWidget {
            background-color: #151E2B;
            alternate-background-color: #1A2637;
            color: #DCE5F1;
            border: 1px solid #2B3A50;
            border-radius: 9px;
            gridline-color: #29384C;
            selection-background-color: #16465D;
            selection-color: #FFFFFF;
        }

        QTableWidget::item {
            background-color: #151E2B;
            padding: 8px;
            border-bottom: 1px solid #253247;
        }

        QTableWidget::item:alternate {
            background-color: #1A2637;
        }

        QTableWidget::item:selected {
            background-color: #16465D;
            color: #FFFFFF;
        }

        QHeaderView {
            background-color: #192536;
        }

        QHeaderView::section {
            background-color: #192536;
            color: #A9BBD2;
            padding: 11px;
            border: none;
            border-bottom: 1px solid #34465D;
            font-weight: bold;
        }

        QTableCornerButton::section {
            background-color: #192536;
            border: none;
        }

        /* ---------- TEXT EDITOR / TERMINAL ---------- */

        QTextEdit {
            background-color: #0D1420;
            color: #B9CBE0;
            border: 1px solid #2A3A50;
            border-radius: 8px;
            padding: 10px;
            selection-background-color: #16465D;
        }

        /* ---------- PROCESS INFORMATION ---------- */

        #ProcessInfo {
            background-color: #1A293C;
            border: 1px solid #344C67;
            border-radius: 8px;
            padding: 12px;
            color: #C5D5E8;
        }

        /* ---------- GROUP BOX ---------- */

        QGroupBox {
            background-color: #151E2B;
            color: #DCE5F1;
            border: 1px solid #2E3D53;
            border-radius: 9px;
            margin-top: 15px;
            padding: 16px 10px 10px 10px;
            font-weight: bold;
        }

        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 7px;
            color: #43D9F5;
            background-color: #151E2B;
        }

        /* ---------- PROGRESS BAR ---------- */

        QProgressBar {
            background-color: #202B3B;
            color: #E6EDF7;
            border: 1px solid #34465D;
            border-radius: 6px;
            text-align: center;
            min-height: 13px;
            max-height: 13px;
        }

        QProgressBar::chunk {
            background-color: #13B8D8;
            border-radius: 5px;
        }

        /* ---------- TABS ---------- */

        #TabButton {
            background-color: #192333;
            color: #91A3BA;
            border: 1px solid #2B3A50;
            padding: 8px 15px;
            font-weight: 600;
        }

        #TabButton:hover {
            background-color: #24354A;
            color: #FFFFFF;
        }

        #TabButtonActive {
            background-color: #163448;
            color: #43D9F5;
            border: 1px solid #27617A;
            border-radius: 6px;
            padding: 8px 15px;
            font-weight: bold;
        }

        /* ---------- ACTION MENU ---------- */

        #RowActionMenu {
            background-color: #192333;
            color: #A9BBD2;
            font-weight: bold;
            border: 1px solid #34465D;
            border-radius: 5px;
        }

        #RowActionMenu:hover {
            background-color: #263B53;
            color: #43D9F5;
        }

        /* ---------- MENUS ---------- */

        QMenu {
            background-color: #192333;
            color: #DCE5F1;
            border: 1px solid #35465E;
            padding: 5px;
        }

        QMenu::item {
            background-color: #192333;
            padding: 8px 24px;
            border-radius: 4px;
        }

        QMenu::item:selected {
            background-color: #16465D;
            color: #43D9F5;
        }

        /* ---------- SCROLLBARS ---------- */

        QScrollBar:vertical {
            background-color: #111722;
            width: 9px;
            margin: 0;
            border: none;
        }

        QScrollBar::handle:vertical {
            background-color: #3A4A61;
            min-height: 30px;
            border-radius: 4px;
        }

        QScrollBar::handle:vertical:hover {
            background-color: #43D9F5;
        }

        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {
            height: 0;
            border: none;
        }

        QScrollBar:horizontal {
            background-color: #111722;
            height: 9px;
            margin: 0;
            border: none;
        }

        QScrollBar::handle:horizontal {
            background-color: #3A4A61;
            min-width: 30px;
            border-radius: 4px;
        }

        QScrollBar::handle:horizontal:hover {
            background-color: #43D9F5;
        }

        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {
            width: 0;
            border: none;
        }

        /* ---------- TOOLTIP ---------- */

        QToolTip {
            background-color: #202F44;
            color: #F1F5F9;
            border: 1px solid #43D9F5;
            padding: 6px 9px;
            border-radius: 5px;
        }

        /* ---------- CHECKBOX ---------- */

        QCheckBox {
            background-color: transparent;
            color: #C5D5E8;
            spacing: 8px;
        }

        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            background-color: #192333;
            border: 1px solid #52647D;
            border-radius: 4px;
        }

        QCheckBox::indicator:checked {
            background-color: #13A8C7;
            border: 1px solid #43D9F5;
        }

        /* ---------- RADIO BUTTON ---------- */

        QRadioButton {
            background-color: transparent;
            color: #C5D5E8;
            spacing: 8px;
        }

        /* ---------- SPLITTER ---------- */

        QSplitter::handle {
            background-color: #29384C;
        }

        QSplitter::handle:hover {
            background-color: #43D9F5;
        }
        

        /* ================= POPUP / DIALOG FIX ================= */

        /* Message Boxes */
        QMessageBox {
            background-color: #151E2B;
            color: #E6EDF7;
            border: 1px solid #344256;
        }

        QMessageBox QLabel {
            background-color: transparent;
            color: #E6EDF7;
            font-size: 13px;
            padding: 8px;
        }

        QMessageBox QPushButton {
            background-color: #00B8D9;
            color: #07131F;
            border: none;
            border-radius: 6px;
            padding: 8px 22px;
            min-width: 75px;
            font-weight: bold;
        }

        QMessageBox QPushButton:hover {
            background-color: #28D7F2;
        }

        QMessageBox QPushButton:pressed {
            background-color: #009BB8;
        }

        /* General Dialogs */
        QDialog {
            background-color: #111722;
            color: #E6EDF7;
        }

        QDialog QLabel {
            color: #E6EDF7;
            background-color: transparent;
        }

        /* Dialog Input Fields */
        QDialog QLineEdit,
        QDialog QComboBox,
        QDialog QTextEdit {
            background-color: #192333;
            color: #E6EDF7;
            border: 1px solid #344256;
            border-radius: 6px;
            padding: 7px;
        }

        /* Dialog Buttons */
        QDialog QPushButton {
            background-color: #00B8D9;
            color: #07131F;
            border: none;
            border-radius: 6px;
            padding: 8px 18px;
            font-weight: bold;
        }

        QDialog QPushButton:hover {
            background-color: #28D7F2;
        }

        /* File Dialog */
        QFileDialog {
            background-color: #111722;
            color: #E6EDF7;
        }

        QFileDialog QLabel {
            color: #E6EDF7;
        }

        QFileDialog QTreeView,
        QFileDialog QListView,
        QFileDialog QTableView {
            background-color: #192333;
            color: #E6EDF7;
            selection-background-color: #16445A;
            selection-color: #FFFFFF;
        }

        /* Context Menu */
        QMenu {
            background-color: #192333;
            color: #E6EDF7;
            border: 1px solid #344256;
            padding: 5px;
        }

        QMenu::item {
            padding: 7px 25px;
        }

        QMenu::item:selected {
            background-color: #16445A;
            color: #FFFFFF;
        }
        """