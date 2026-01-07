"""Progress state persistence for long-running operations.

This module provides utilities to save and restore progress for operations
that may need to be resumed, such as listing unused payees which can be
rate-limited by the YNAB API.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import TypedDict


class ProgressStateData(TypedDict):
    """Serializable progress state."""

    operation: str
    budget_id: str
    last_processed_name: str
    last_processed_index: int
    total_items: int
    processed_count: int
    unused_count: int
    timestamp: str


class ProgressState:
    """Manages progress state for resumable operations.

    Progress is saved to a JSON file in the user's config directory,
    keyed by operation type and budget ID.
    """

    def __init__(
        self,
        operation: str,
        budget_id: str,
        state_dir: Path | None = None,
    ):
        self._operation = operation
        self._budget_id = budget_id
        self._state_dir = state_dir or self._default_state_dir()
        self._state_file = self._state_dir / f"{operation}_{budget_id}.json"

        self.last_processed_name: str = ""
        self.last_processed_index: int = -1
        self.total_items: int = 0
        self.processed_count: int = 0
        self.unused_count: int = 0
        self.timestamp: datetime | None = None

    @staticmethod
    def _default_state_dir() -> Path:
        """Get the default state directory."""
        config_dir = Path.home() / ".config" / "ynab-cli" / "progress"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir

    def load(self) -> bool:
        """Load progress state from disk.

        Returns:
            True if state was loaded successfully, False otherwise.
        """
        if not self._state_file.exists():
            return False

        try:
            with self._state_file.open("r") as f:
                data: ProgressStateData = json.load(f)

            # Verify this is the right operation and budget
            if data.get("operation") != self._operation or data.get("budget_id") != self._budget_id:
                return False

            self.last_processed_name = data.get("last_processed_name", "")
            self.last_processed_index = data.get("last_processed_index", -1)
            self.total_items = data.get("total_items", 0)
            self.processed_count = data.get("processed_count", 0)
            self.unused_count = data.get("unused_count", 0)

            timestamp_str = data.get("timestamp")
            if timestamp_str:
                self.timestamp = datetime.fromisoformat(timestamp_str)

            return True

        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return False

    def save(self) -> None:
        """Save progress state to disk."""
        self._state_file.parent.mkdir(parents=True, exist_ok=True)

        data: ProgressStateData = {
            "operation": self._operation,
            "budget_id": self._budget_id,
            "last_processed_name": self.last_processed_name,
            "last_processed_index": self.last_processed_index,
            "total_items": self.total_items,
            "processed_count": self.processed_count,
            "unused_count": self.unused_count,
            "timestamp": datetime.now().isoformat(),
        }

        with self._state_file.open("w") as f:
            json.dump(data, f, indent=2)

    def clear(self) -> None:
        """Clear the saved progress state."""
        if self._state_file.exists():
            self._state_file.unlink()

        self.last_processed_name = ""
        self.last_processed_index = -1
        self.total_items = 0
        self.processed_count = 0
        self.unused_count = 0
        self.timestamp = None

    def update(
        self,
        name: str,
        index: int,
        total: int | None = None,
        increment_processed: bool = True,
        increment_unused: bool = False,
    ) -> None:
        """Update progress state.

        Args:
            name: Name of the last processed item.
            index: Index of the last processed item.
            total: Total number of items (updated if provided).
            increment_processed: Whether to increment the processed count.
            increment_unused: Whether to increment the unused count.
        """
        self.last_processed_name = name
        self.last_processed_index = index

        if total is not None:
            self.total_items = total

        if increment_processed:
            self.processed_count += 1

        if increment_unused:
            self.unused_count += 1

        # Auto-save periodically (every 10 items)
        if self.processed_count % 10 == 0:
            self.save()

    def get_resume_info(self) -> str:
        """Get a human-readable summary of the saved progress."""
        if not self.last_processed_name:
            return "No saved progress found."

        time_str = self.timestamp.strftime("%Y-%m-%d %H:%M:%S") if self.timestamp else "unknown"
        return (
            f"Found saved progress from {time_str}:\n"
            f"  Last processed: {self.last_processed_name}\n"
            f"  Progress: {self.processed_count}/{self.total_items} items\n"
            f"  Unused found: {self.unused_count}"
        )

    def should_skip(self, name: str, index: int) -> bool:
        """Check if an item should be skipped based on resume state.

        Args:
            name: Name of the item to check.
            index: Index of the item to check.

        Returns:
            True if the item should be skipped (already processed).
        """
        # If we have a last processed index, use that for accurate comparison
        if self.last_processed_index >= 0:
            return index <= self.last_processed_index

        # Fall back to name comparison (less reliable if names changed)
        if self.last_processed_name:
            return name <= self.last_processed_name

        return False

