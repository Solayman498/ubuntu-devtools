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

    def _connect(self):
        return sqlite3.connect(self.database_path)

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
    # Register one project
    # -----------------------------
    def register_project(self, project):
        resolved_path = str(Path(project["path"]).resolve())

        # Do not register an ignored project.
        if resolved_path in self.get_ignored_paths():
            return

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
                project["confidence"],
                "Discovered",
            ))

            connection.commit()

    # -----------------------------
    # Register multiple projects
    # -----------------------------
    def register_projects(self, projects):
        for project in projects:
            self.register_project(project)

    # -----------------------------
    # Replace complete project list
    # -----------------------------
    def replace_projects(self, projects):
        ignored_paths = self.get_ignored_paths()

        with self._connect() as connection:
            connection.execute("DELETE FROM projects")

            for project in projects:
                resolved_path = str(Path(project["path"]).resolve())

                if any(
                    resolved_path == ignored
                    or ignored in Path(resolved_path).parents
                    for ignored in ignored_paths
                ):
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
                """, (
                    project["name"],
                    resolved_path,
                    project["type"],
                    project["confidence"],
                    "Discovered",
                ))

            connection.commit()

    # -----------------------------
    # Synchronize one scanned folder
    # -----------------------------
    def sync_projects_in_path(self, projects, root_path):
        root = Path(root_path).resolve()
        ignored_paths = self.get_ignored_paths()

        with self._connect() as connection:
            existing_rows = connection.execute(
                "SELECT path FROM projects"
            ).fetchall()

            # Remove stale entries only inside the scanned folder.
            for (existing_path,) in existing_rows:
                existing = Path(existing_path).resolve()

                if existing == root or root in existing.parents:
                    if not any(
                        existing == ignored
                        or ignored in existing.parents
                        for ignored in ignored_paths
                    ):
                        connection.execute(
                            "DELETE FROM projects WHERE path = ?",
                            (existing_path,),
                        )

            # Add or update the projects discovered in this scan.
            for project in projects:
                resolved_path = str(Path(project["path"]).resolve())

                if any(
                    resolved_path == ignored
                    or ignored in Path(resolved_path).parents
                    for ignored in ignored_paths
                ):
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
                    project["confidence"],
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
    # Ignore project permanently
    # -----------------------------
    def ignore_project(self, path, name=None):
        resolved_path = str(Path(path).resolve())

        if name is None:
            name = Path(resolved_path).name

        with self._connect() as connection:
            connection.execute("""
                INSERT INTO ignored_projects (path, name)
                VALUES (?, ?)

                ON CONFLICT(path)
                DO UPDATE SET name = excluded.name
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
            str(Path(row["path"]).resolve())
            for row in self.get_ignored_projects()
        }

    # -----------------------------
    # Restore ignored project
    # -----------------------------
    def restore_ignored_project(self, path):
        resolved_path = str(Path(path).resolve())

        with self._connect() as connection:
            connection.execute(
                "DELETE FROM ignored_projects WHERE path = ?",
                (resolved_path,),
            )
            connection.commit()