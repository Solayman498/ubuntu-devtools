import sqlite3
from pathlib import Path


class ProjectRegistry:

    def __init__(self):
        self.data_directory = (
            Path.home() / ".local" / "share" / "ubuntu-devtools"
        )

        self.data_directory.mkdir(
            parents=True,
            exist_ok=True
        )

        self.database_path = (
            self.data_directory / "projects.db"
        )

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

            connection.commit()

    def register_project(self, project):

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
                project["path"],
                project["type"],
                project["confidence"],
                "Discovered"
            ))

            connection.commit()

    def register_projects(self, projects):

        for project in projects:
            self.register_project(project)

    def get_projects(self):

        with self._connect() as connection:

            connection.row_factory = sqlite3.Row

            rows = connection.execute("""
                SELECT *
                FROM projects
                ORDER BY name
            """).fetchall()

        return [dict(row) for row in rows]

    def get_project(self, project_id):

        with self._connect() as connection:

            connection.row_factory = sqlite3.Row

            row = connection.execute("""
                SELECT *
                FROM projects
                WHERE id = ?
            """, (project_id,)).fetchone()

        if row is None:
            return None

        return dict(row)

    def remove_project(self, project_id):

        with self._connect() as connection:

            connection.execute("""
                DELETE FROM projects
                WHERE id = ?
            """, (project_id,))

            connection.commit()

    def update_status(self, project_id, status):

        with self._connect() as connection:

            connection.execute("""
                UPDATE projects
                SET status = ?
                WHERE id = ?
            """, (status, project_id))

            connection.commit()