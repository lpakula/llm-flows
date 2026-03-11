"""Task service -- CRUD scoped to project."""

from typing import Optional

from sqlalchemy.orm import Session

from ..db.models import Task, TaskType


class TaskService:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        project_id: str,
        name: str,
        description: str = "",
        task_type: TaskType = TaskType.FEATURE,
    ) -> Task:
        """Create a new task with a required title."""
        task = Task(
            project_id=project_id,
            name=name,
            description=description,
            type=task_type,
        )
        self.session.add(task)
        self.session.commit()
        return task

    def get(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        return self.session.query(Task).filter_by(id=task_id).first()

    def list_by_project(self, project_id: str) -> list[Task]:
        """List all tasks for a project ordered by creation date."""
        return (
            self.session.query(Task)
            .filter_by(project_id=project_id)
            .order_by(Task.created_at)
            .all()
        )

    def update(self, task_id: str, **kwargs) -> Optional[Task]:
        """Update arbitrary fields on a task."""
        task = self.get(task_id)
        if not task:
            return None
        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)
        self.session.commit()
        return task

    def delete(self, task_id: str) -> bool:
        """Delete a task."""
        task = self.get(task_id)
        if not task:
            return False
        self.session.delete(task)
        self.session.commit()
        return True
