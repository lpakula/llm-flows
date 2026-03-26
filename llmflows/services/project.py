"""Project registry service."""

from typing import Optional

from sqlalchemy.orm import Session

from ..db.models import Project, ProjectSettings


class ProjectService:
    def __init__(self, session: Session):
        self.session = session

    def register(self, name: str, path: str, git_repo: bool = True) -> Project:
        """Register a project in the central database."""
        existing = self.session.query(Project).filter_by(path=path).first()
        if existing:
            settings = self.session.query(ProjectSettings).filter_by(
                project_id=existing.id
            ).first()
            if not settings:
                settings = ProjectSettings(
                    project_id=existing.id,
                    is_git_repo=git_repo,
                )
                self.session.add(settings)
                self.session.commit()
            return existing

        project = Project(name=name, path=path)
        self.session.add(project)
        self.session.flush()

        settings = ProjectSettings(
            project_id=project.id,
            is_git_repo=git_repo,
        )
        self.session.add(settings)
        self.session.commit()
        return project

    def unregister(self, project_id: str) -> bool:
        """Remove a project from the registry."""
        project = self.session.query(Project).filter_by(id=project_id).first()
        if not project:
            return False
        self.session.delete(project)
        self.session.commit()
        return True

    def update(self, project_id: str, **kwargs) -> Optional[Project]:
        """Update fields on a project."""
        project = self.get(project_id)
        if not project:
            return None
        for key, value in kwargs.items():
            if hasattr(project, key):
                setattr(project, key, value)
        self.session.commit()
        return project

    def list_all(self) -> list[Project]:
        """List all registered projects."""
        return self.session.query(Project).order_by(Project.created_at).all()

    def get(self, project_id: str) -> Optional[Project]:
        """Get a project by ID."""
        return self.session.query(Project).filter_by(id=project_id).first()

    def get_by_path(self, path: str) -> Optional[Project]:
        """Get a project by its repo root path."""
        return self.session.query(Project).filter_by(path=path).first()

    def resolve_current(self) -> Optional[Project]:
        """Resolve the current project from the git root or working directory."""
        from ..config import get_repo_root, find_project_dir
        repo_root = get_repo_root()
        if repo_root is not None:
            return self.get_by_path(str(repo_root))
        project_dir = find_project_dir()
        if project_dir is not None:
            return self.get_by_path(str(project_dir.parent))
        return None
