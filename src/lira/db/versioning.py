"""Git-like database versioning for L.I.R.A.

Provides event sourcing and snapshot capabilities for:
- Tracking all changes to financial data
- Creating named checkpoints (commits)
- Rolling back to previous states
- Auditing who changed what and when
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for version events."""


logger = logging.getLogger(__name__)


class VersionEventType(str, Enum):
    """Types of version events."""

    SNAPSHOT = "snapshot"
    ROLLBACK = "rollback"
    CHECKPOINT = "checkpoint"
    TAG = "tag"


@dataclass
class DiffResult:
    """Represents the difference between current and proposed state."""

    current_state: dict[str, Any]
    proposed_state: dict[str, Any]
    changes: list[Change]
    is_safe: bool

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "current_state": self.current_state,
            "proposed_state": self.proposed_state,
            "changes": [c.to_dict() for c in self.changes],
            "is_safe": self.is_safe,
        }


@dataclass
class Change:
    """Represents a single change in a diff."""

    operation: str
    table: str
    record_id: int | None
    field: str
    old_value: Any
    new_value: Any

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "operation": self.operation,
            "table": self.table,
            "record_id": self.record_id,
            "field": self.field,
            "old_value": str(self.old_value) if self.old_value is not None else None,
            "new_value": str(self.new_value) if self.new_value is not None else None,
        }


class VersionEvent(Base):
    """Event log entry for tracking changes."""

    __tablename__ = "version_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid.uuid4()), unique=True, nullable=False
    )
    event_type: Mapped[VersionEventType] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    parent_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    author: Mapped[str] = mapped_column(String(100), default="system")


class VersioningService:
    """Service for git-like database versioning.

    Provides:
    - Event sourcing (append-only log of all changes)
    - Snapshots (point-in-time state captures)
    - Rollbacks (revert to previous state)
    - Tags (named checkpoints)
    """

    def __init__(self, session: Any) -> None:
        self.session = session

    def create_snapshot(
        self,
        description: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create a point-in-time snapshot of the database.

        Args:
            description: Description of the snapshot
            metadata: Additional metadata

        Returns:
            Event ID of the created snapshot
        """
        from lira.db.models import Base

        event_id = str(uuid.uuid4())

        snapshot_data = {}
        for table_name in Base.metadata.tables:
            table = Base.metadata.tables[table_name]
            results = self.session.execute(table.select()).fetchall()
            snapshot_data[table_name] = [dict(row._mapping) for row in results]

        event = VersionEvent(
            event_id=event_id,
            event_type=VersionEventType.SNAPSHOT,
            description=description,
            snapshot_data=snapshot_data,
            metadata=metadata,
        )

        self.session.add(event)
        self.session.commit()

        logger.info("Created snapshot: %s - %s", event_id, description)
        return event_id

    def create_tag(
        self,
        name: str,
        description: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create a named tag (checkpoint).

        Args:
            name: Tag name
            description: Description of the tag
            metadata: Additional metadata

        Returns:
            Event ID of the created tag
        """
        event_id = str(uuid.uuid4())

        event = VersionEvent(
            event_id=event_id,
            event_type=VersionEventType.TAG,
            description=description,
            metadata={**(metadata or {}), "tag_name": name},
        )

        self.session.add(event)
        self.session.commit()

        logger.info("Created tag: %s - %s", name, description)
        return event_id

    def rollback_to(
        self,
        event_id: str,
        description: str | None = None,
    ) -> bool:
        """Rollback database to a previous snapshot.

        Args:
            event_id: Event ID of the snapshot to rollback to
            description: Reason for rollback

        Returns:
            True if successful
        """
        event = self.session.query(VersionEvent).filter_by(event_id=event_id).first()

        if not event:
            logger.error("Event not found: %s", event_id)
            return False

        if event.event_type != VersionEventType.SNAPSHOT:
            logger.error("Can only rollback to snapshot events")
            return False

        snapshot_data = event.snapshot_data
        if not snapshot_data:
            logger.error("No snapshot data in event: %s", event_id)
            return False

        rollback_event_id = str(uuid.uuid4())

        for table_name, records in snapshot_data.items():
            table = Base.metadata.tables.get(table_name)
            if not table:
                continue

            self.session.execute(table.delete())

            for record in records:
                record.pop("id", None)
                self.session.execute(table.insert().values(**record))

        rollback_event = VersionEvent(
            event_id=rollback_event_id,
            event_type=VersionEventType.ROLLBACK,
            description=description or f"Rolled back to {event_id}",
            parent_event_id=event_id,
            metadata={"rollback_from": event_id},
        )

        self.session.add(rollback_event)
        self.session.commit()

        logger.info(
            "Rolled back to event: %s, created rollback: %s",
            event_id,
            rollback_event_id,
        )
        return True

    def get_history(
        self,
        limit: int = 50,
        event_type: VersionEventType | None = None,
    ) -> list[VersionEvent]:
        """Get event history.

        Args:
            limit: Maximum number of events to return
            event_type: Filter by event type

        Returns:
            List of version events
        """
        query = self.session.query(VersionEvent)

        if event_type:
            query = query.filter_by(event_type=event_type)

        return query.order_by(VersionEvent.created_at.desc()).limit(limit).all()

    def generate_diff(
        self,
        current_state: dict[str, Any],
        proposed_state: dict[str, Any],
    ) -> DiffResult:
        """Generate a diff between current and proposed state.

        Args:
            current_state: Current database state
            proposed_state: Proposed changes

        Returns:
            DiffResult with all changes
        """
        changes: list[Change] = []

        for table, records in proposed_state.items():
            current_table = current_state.get(table, [])

            if isinstance(records, list):
                for record in records:
                    record_id = record.get("id")
                    op = record.get("_operation", "update")

                    if op == "delete":
                        changes.append(
                            Change(
                                operation="delete",
                                table=table,
                                record_id=record_id,
                                field="*",
                                old_value=record,
                                new_value=None,
                            )
                        )
                    elif op == "insert":
                        changes.append(
                            Change(
                                operation="insert",
                                table=table,
                                record_id=None,
                                field="*",
                                old_value=None,
                                new_value=record,
                            )
                        )
                    else:
                        current_record = next(
                            (r for r in current_table if r.get("id") == record_id),
                            None,
                        )
                        if current_record:
                            for key, value in record.items():
                                if key != "id" and key != "_operation":
                                    old_val = current_record.get(key)
                                    if old_val != value:
                                        changes.append(
                                            Change(
                                                operation="update",
                                                table=table,
                                                record_id=record_id,
                                                field=key,
                                                old_value=old_val,
                                                new_value=value,
                                            )
                                        )

        is_safe = all(c.operation in ("insert", "update") for c in changes)

        return DiffResult(
            current_state=current_state,
            proposed_state=proposed_state,
            changes=changes,
            is_safe=is_safe,
        )

    def export_snapshot(self, file_path: str | Path) -> None:
        """Export the latest snapshot to a file.

        Args:
            file_path: Path to export to
        """
        events = self.get_history(limit=1, event_type=VersionEventType.SNAPSHOT)

        if not events:
            raise ValueError("No snapshots found")

        snapshot = events[0]
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            json.dump(
                {
                    "event_id": snapshot.event_id,
                    "description": snapshot.description,
                    "created_at": snapshot.created_at.isoformat(),
                    "data": snapshot.snapshot_data,
                },
                f,
                indent=2,
            )

        logger.info("Exported snapshot to: %s", file_path)

    def import_snapshot(self, file_path: str | Path) -> str:
        """Import a snapshot from a file.

        Args:
            file_path: Path to import from

        Returns:
            Event ID of the imported snapshot
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Snapshot file not found: {file_path}")

        with open(path) as f:
            data = json.load(f)

        event = VersionEvent(
            event_id=data["event_id"],
            event_type=VersionEventType.SNAPSHOT,
            description=f"Imported: {data['description']}",
            snapshot_data=data["data"],
            metadata={"imported": True},
        )

        self.session.add(event)
        self.session.commit()

        logger.info("Imported snapshot: %s", data["event_id"])
        return data["event_id"]


from lira.db.models import Base
