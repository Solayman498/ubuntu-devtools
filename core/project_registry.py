import sqlite3
from pathlib import Path


class ProjectRegistry:
    def __init__(self):
        self.data_directory = (
            Path.home() / ".local" / "share" / "ubuntu-devtools"
        )
        self.data_directory.mkdir(parents=True, exist_ok=True)

        self.database_path = self.data_directory / "projects.db"
        self._create_database()

    # -----------------------------
    # Database connection
    # -----------------------------
    def _connect(self):
        return sqlite3.connect(self.database_path)

    # -----------------------------
    # Create database tables
    # -----------------------------
    def _create_database(self):
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    project_type TEXT NOT NULL,
                    confidence TEXT,
                    status TEXT DEFAULT 'Discovered',
                    last_scanned TEXT,
                    last_launched TEXT
                )
            """)

            connection.execute("""
                CREATE TABLE IF NOT EXISTS ignored_projects (
                    path TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    ignored_at TEXT DEFAULT (datetime('now'))
                )
            """)

            connection.commit()

    # -----------------------------
    # Normalize a project path
    # -----------------------------
    @staticmethod
    def _resolve_path(path):
        return str(Path(path).expanduser().resolve())

    # -----------------------------
    # Check whether a path is ignored
    # -----------------------------
    def _is_ignored(self, path, ignored_paths=None):
        resolved_path = Path(self._resolve_path(path))

        if ignored_paths is None:
            ignored_paths = self.get_ignored_paths()

        for ignored_path in ignored_paths:
            ignored = Path(ignored_path).resolve()

            # The project itself is ignored.
            # Projects inside an ignored directory are also ignored.
            if resolved_path == ignored or ignored in resolved_path.parents:
                return True

        return False

    # -----------------------------
    # Register one project
    # -----------------------------
    def register_project(self, project):
        resolved_path = self._resolve_path(project["path"])

        # Do not register ignored projects.
        if self._is_ignored(resolved_path):
            return

        confidence = project.get("confidence", "Medium")

        # Preserve the manual registration marker.
        is_manual = confidence == "Manual"

        with self._connect() as connection:
            connection.execute("""
                INSERT INTO projects (
                    name,
                    path,
                    project_type,
                    confidence,
                    status,
                    last_scanned
                )
                VALUES (?, ?, ?, ?, ?, datetime('now'))

                ON CONFLICT(path)
                DO UPDATE SET
                    name = excluded.name,
                    project_type = excluded.project_type,
                    confidence = excluded.confidence,
                    last_scanned = excluded.last_scanned
            """, (
                project["name"],
                resolved_path,
                project["type"],
                confidence,
                "Discovered",
            ))

            # Keep manually registered projects marked as Manual.
            # The INSERT/UPDATE above already uses the supplied confidence.
            connection.commit()

    # -----------------------------
    # Register multiple projects
    # -----------------------------
    def register_projects(self, projects):
        for project in projects:
            self.register_project(project)

    # -----------------------------
    # Replace complete project list
    # Preserves manual projects
    # -----------------------------
    def replace_projects(self, projects):
        ignored_paths = self.get_ignored_paths()

        # Save existing manually registered projects before replacement.
        with self._connect() as connection:
            manual_rows = connection.execute("""
                SELECT
                    name,
                    path,
                    project_type,
                    confidence,
                    status,
                    last_scanned,
                    last_launched
                FROM projects
                WHERE confidence = 'Manual'
            """).fetchall()

            # Replace the discovered list.
            connection.execute("DELETE FROM projects")

            discovered_paths = set()

            # Insert newly discovered projects.
            for project in projects:
                resolved_path = self._resolve_path(project["path"])

                if self._is_ignored(resolved_path, ignored_paths):
                    continue

                discovered_paths.add(resolved_path)

                connection.execute("""
                    INSERT INTO projects (
                        name,
                        path,
                        project_type,
                        confidence,
                        status,
                        last_scanned
                    )
                    VALUES (?, ?, ?, ?, ?, datetime('now'))

                    ON CONFLICT(path)
                    DO UPDATE SET
                        name = excluded.name,
                        project_type = excluded.project_type,
                        confidence = excluded.confidence,
                        last_scanned = excluded.last_scanned
                """, (
                    project["name"],
                    resolved_path,
                    project["type"],
                    project.get("confidence", "Medium"),
                    "Discovered",
                ))

            # Restore manual projects not rediscovered by this scan.
            for row in manual_rows:
                (
                    name,
                    path,
                    project_type,
                    confidence,
                    status,
                    last_scanned,
                    last_launched,
                ) = row

                resolved_path = self._resolve_path(path)

                if resolved_path in discovered_paths:
                    continue

                if self._is_ignored(resolved_path, ignored_paths):
                    continue

                connection.execute("""
                    INSERT INTO projects (
                        name,
                        path,
                        project_type,
                        confidence,
                        status,
                        last_scanned,
                        last_launched
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)

                    ON CONFLICT(path) DO NOTHING
                """, (
                    name,
                    resolved_path,
                    project_type,
                    confidence,
                    status,
                    last_scanned,
                    last_launched,
                ))

            connection.commit()

    # -----------------------------
    # Synchronize one scanned folder
    # Preserves manual projects
    # -----------------------------
    def sync_projects_in_path(self, projects, root_path):
        root = Path(self._resolve_path(root_path))
        ignored_paths = self.get_ignored_paths()

        with self._connect() as connection:
            existing_rows = connection.execute("""
                SELECT path, confidence
                FROM projects
            """).fetchall()

            # Remove stale discovered projects only inside the scanned folder.
            # Manual projects are preserved.
            for existing_path, confidence in existing_rows:
                existing = Path(self._resolve_path(existing_path))

                is_inside_root = (
                    existing == root or root in existing.parents
                )

                if not is_inside_root:
                    continue

                if confidence == "Manual":
                    continue

                if self._is_ignored(existing, ignored_paths):
                    continue

                connection.execute(
                    "DELETE FROM projects WHERE path = ?",
                    (existing_path,),
                )

            # Add or update projects found during the scan.
            for project in projects:
                resolved_path = self._resolve_path(project["path"])

                if self._is_ignored(resolved_path, ignored_paths):
                    continue

                connection.execute("""
                    INSERT INTO projects (
                        name,
                        path,
                        project_type,
                        confidence,
                        status,
                        last_scanned
                    )
                    VALUES (?, ?, ?, ?, ?, datetime('now'))

                    ON CONFLICT(path)
                    DO UPDATE SET
                        name = excluded.name,
                        project_type = excluded.project_type,
                        confidence = excluded.confidence,
                        last_scanned = excluded.last_scanned
                """, (
                    project["name"],
                    resolved_path,
                    project["type"],
                    project.get("confidence", "Medium"),
                    "Discovered",
                ))

            connection.commit()

    # -----------------------------
    # Get all registered projects
    # -----------------------------
    def get_projects(self):
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row

            rows = connection.execute("""
                SELECT *
                FROM projects
                ORDER BY name
            """).fetchall()

        return [dict(row) for row in rows]

    # -----------------------------
    # Get one project by ID
    # -----------------------------
    def get_project(self, project_id):
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row

            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()

        return dict(row) if row else None

    # -----------------------------
    # Remove project from app registry
    # Does not delete actual files
    # -----------------------------
    def remove_project(self, project_id):
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM projects WHERE id = ?",
                (project_id,),
            )

            connection.commit()

    # -----------------------------
    # Update project status
    # -----------------------------
    def update_status(self, project_id, status):
        with self._connect() as connection:
            connection.execute(
                "UPDATE projects SET status = ? WHERE id = ?",
                (status, project_id),
            )

            connection.commit()

    # -----------------------------
    # Update last launched time
    # -----------------------------
    def update_last_launched(self, project_id):
        with self._connect() as connection:
            connection.execute("""
                UPDATE projects
                SET
                    last_launched = datetime('now'),
                    status = 'Launched'
                WHERE id = ?
            """, (project_id,))

            connection.commit()

    # -----------------------------
    # Ignore project permanently
    # -----------------------------
    def ignore_project(self, path, name=None):
        resolved_path = self._resolve_path(path)

        if name is None:
            name = Path(resolved_path).name

        with self._connect() as connection:
            connection.execute("""
                INSERT INTO ignored_projects (path, name)
                VALUES (?, ?)

                ON CONFLICT(path)
                DO UPDATE SET
                    name = excluded.name
            """, (resolved_path, name))

            # Remove the project from the visible registry.
            connection.execute(
                "DELETE FROM projects WHERE path = ?",
                (resolved_path,),
            )

            connection.commit()

    # -----------------------------
    # Get ignored projects
    # -----------------------------
    def get_ignored_projects(self):
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row

            rows = connection.execute("""
                SELECT path, name, ignored_at
                FROM ignored_projects
                ORDER BY name
            """).fetchall()

        return [dict(row) for row in rows]

    # -----------------------------
    # Get ignored paths
    # -----------------------------
    def get_ignored_paths(self):
        return {
            self._resolve_path(row["path"])
            for row in self.get_ignored_projects()
        }

    # -----------------------------
    # Restore ignored project
    # Removes ignore rule only
    # -----------------------------
    def restore_ignored_project(self, path):
        resolved_path = self._resolve_path(path)

        with self._connect() as connection:
            connection.execute(
                "DELETE FROM ignored_projects WHERE path = ?",
                (resolved_path,),
            )

            connection.commit()