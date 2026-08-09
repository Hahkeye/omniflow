"""Cross-session action-item inbox with completion tracking."""
from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .history import DEFAULT_DIARY_DIR, list_entries, load_analysis_data

ACTIONS_FILE = "actions.json"


def _action_id(entry_id: str, text: str) -> str:
    h = hashlib.sha1(f"{entry_id}|{text.strip().lower()}".encode("utf-8")).hexdigest()[:12]
    return f"a_{h}"


@dataclass
class ActionItem:
    id: str
    text: str
    entry_id: str
    source: str = "analysis"  # analysis | manual
    done: bool = False
    created_at: str = ""
    done_at: str | None = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ActionItem":
        return cls(
            id=d.get("id") or _action_id(d.get("entry_id", ""), d.get("text", "")),
            text=(d.get("text") or "").strip(),
            entry_id=d.get("entry_id") or "",
            source=d.get("source") or "analysis",
            done=bool(d.get("done")),
            created_at=d.get("created_at") or "",
            done_at=d.get("done_at"),
            tags=list(d.get("tags") or []),
        )


class ActionInbox:
    """Persistent open/done action items under ~/diary/actions.json."""

    def __init__(self, diary_dir: Path | None = None):
        self.root = Path(diary_dir) if diary_dir else DEFAULT_DIARY_DIR
        self.path = self.root / ACTIONS_FILE
        self.items: dict[str, ActionItem] = {}
        self._load()

    def _load(self) -> None:
        self.items = {}
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        for raw in data.get("items") or []:
            if not isinstance(raw, dict) or not raw.get("text"):
                continue
            item = ActionItem.from_dict(raw)
            self.items[item.id] = item

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "items": [i.to_dict() for i in sorted(
                self.items.values(),
                key=lambda x: (x.done, x.created_at or "", x.text),
            )],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def sync_from_history(self) -> int:
        """Pull new action_items from analysis files; keep existing done flags."""
        added = 0
        now = datetime.now().isoformat(timespec="seconds")
        for entry in list_entries(self.root, limit=None):
            analysis = load_analysis_data(entry)
            kp = analysis.get("key_points", analysis) if analysis else {}
            if not isinstance(kp, dict):
                continue
            for text in kp.get("action_items") or []:
                text = str(text).strip()
                if not text:
                    continue
                aid = _action_id(entry.id, text)
                if aid in self.items:
                    continue
                self.items[aid] = ActionItem(
                    id=aid,
                    text=text,
                    entry_id=entry.id,
                    source="analysis",
                    done=False,
                    created_at=entry.created_at or now,
                )
                added += 1
        if added:
            self.save()
        return added

    def add_manual(self, text: str, entry_id: str = "", tags: list[str] | None = None) -> ActionItem:
        text = text.strip()
        if not text:
            raise ValueError("Action text required")
        now = datetime.now().isoformat(timespec="seconds")
        aid = _action_id(entry_id or "manual", text + now)
        item = ActionItem(
            id=aid,
            text=text,
            entry_id=entry_id or "",
            source="manual",
            created_at=now,
            tags=list(tags or []),
        )
        self.items[aid] = item
        self.save()
        return item

    def mark_done(self, action_id: str, done: bool = True) -> ActionItem:
        item = self._resolve(action_id)
        item.done = done
        item.done_at = datetime.now().isoformat(timespec="seconds") if done else None
        self.save()
        return item

    def remove(self, action_id: str) -> bool:
        item = self._resolve(action_id)
        del self.items[item.id]
        self.save()
        return True

    def _resolve(self, action_id: str) -> ActionItem:
        if action_id in self.items:
            return self.items[action_id]
        # prefix match
        matches = [i for i in self.items if i.startswith(action_id) or action_id in i]
        if len(matches) == 1:
            return self.items[matches[0]]
        # match by text substring
        text_matches = [
            it for it in self.items.values()
            if action_id.lower() in it.text.lower() or action_id.lower() in it.id.lower()
        ]
        if len(text_matches) == 1:
            return text_matches[0]
        raise ValueError(f"Action not found: {action_id}")

    def list_items(
        self,
        *,
        include_done: bool = False,
        entry_id: str | None = None,
        limit: int | None = 100,
    ) -> list[ActionItem]:
        items = list(self.items.values())
        if not include_done:
            items = [i for i in items if not i.done]
        if entry_id:
            items = [i for i in items if i.entry_id == entry_id]
        items.sort(key=lambda x: (x.done, x.created_at or "", x.text))
        if limit is not None:
            items = items[:limit]
        return items


def inbox_for_api(
    *,
    include_done: bool = False,
    sync: bool = True,
    diary_dir: Path | None = None,
) -> dict[str, Any]:
    box = ActionInbox(diary_dir)
    added = box.sync_from_history() if sync else 0
    open_items = box.list_items(include_done=False)
    done_items = box.list_items(include_done=True)
    done_only = [i for i in done_items if i.done]
    return {
        "synced_new": added,
        "open": [i.to_dict() for i in open_items],
        "done": [i.to_dict() for i in done_only],
        "open_count": len(open_items),
        "done_count": len(done_only),
    }
