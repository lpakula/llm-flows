"""Space registry service."""

from typing import Optional

from sqlalchemy.orm import Session

from ..db.models import Space


class SpaceService:
    def __init__(self, session: Session):
        self.session = session

    def register(self, name: str, path: str) -> Space:
        """Register a space in the central database."""
        existing = self.session.query(Space).filter_by(path=path).first()
        if existing:
            return existing

        space = Space(name=name, path=path)
        self.session.add(space)
        self.session.commit()

        return space

    def unregister(self, space_id: str) -> bool:
        """Remove a space from the registry."""
        space = self.session.query(Space).filter_by(id=space_id).first()
        if not space:
            return False
        self.session.delete(space)
        self.session.commit()
        return True

    def update(self, space_id: str, **kwargs) -> Optional[Space]:
        """Update fields on a space."""
        space = self.get(space_id)
        if not space:
            return None
        for key, value in kwargs.items():
            if hasattr(space, key):
                setattr(space, key, value)
        self.session.commit()
        return space

    def list_all(self) -> list[Space]:
        """List all registered spaces."""
        return self.session.query(Space).order_by(Space.created_at).all()

    def get(self, space_id: str) -> Optional[Space]:
        """Get a space by ID."""
        return self.session.query(Space).filter_by(id=space_id).first()

    def get_by_path(self, path: str) -> Optional[Space]:
        """Get a space by its root path."""
        return self.session.query(Space).filter_by(path=path).first()

    def resolve_current(self) -> Optional[Space]:
        """Resolve the current space from the git root or working directory."""
        from ..config import get_repo_root, find_space_dir
        repo_root = get_repo_root()
        if repo_root is not None:
            return self.get_by_path(str(repo_root))
        space_dir = find_space_dir()
        if space_dir is not None:
            return self.get_by_path(str(space_dir.parent))
        return None
