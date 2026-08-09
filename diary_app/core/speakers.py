"""Speaker naming and cross-session memory.

Models emit anonymous labels (Speaker 1 / S01). This module lets users:
- rename labels on a specific history entry
- keep a roster of known people
- optionally remember defaults (e.g. Speaker 1 → Me) for future sessions
- filter history by person name
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .history import DEFAULT_DIARY_DIR, DiaryEntry, get_entry, list_entries, load_transcript_data

SPEAKERS_FILE = "speakers.json"


@dataclass
class Person:
    id: str
    name: str
    created_at: str = ""
    # How often this name was used (for suggestions)
    use_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Person":
        return cls(
            id=d.get("id") or f"p_{uuid.uuid4().hex[:8]}",
            name=(d.get("name") or "").strip(),
            created_at=d.get("created_at") or "",
            use_count=int(d.get("use_count") or 0),
        )


@dataclass
class SpeakerStore:
    """Persistent roster + global defaults under ~/diary/speakers.json."""
    people: list[Person] = field(default_factory=list)
    # Default raw_label → display name applied when an entry has no map
    global_defaults: dict[str, str] = field(default_factory=dict)
    # Optional: last renames per raw label across sessions (memory)
    recent_by_label: dict[str, str] = field(default_factory=dict)
    path: Path | None = None

    def to_dict(self) -> dict:
        return {
            "people": [p.to_dict() for p in self.people],
            "global_defaults": dict(self.global_defaults),
            "recent_by_label": dict(self.recent_by_label),
        }

    @classmethod
    def load(cls, diary_dir: Path | None = None) -> "SpeakerStore":
        root = Path(diary_dir) if diary_dir else DEFAULT_DIARY_DIR
        path = root / SPEAKERS_FILE
        store = cls(path=path)
        if not path.exists():
            return store
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return store
        store.people = [Person.from_dict(p) for p in data.get("people") or [] if p.get("name")]
        store.global_defaults = {
            str(k): str(v) for k, v in (data.get("global_defaults") or {}).items() if v
        }
        store.recent_by_label = {
            str(k): str(v) for k, v in (data.get("recent_by_label") or {}).items() if v
        }
        return store

    def save(self) -> None:
        if self.path is None:
            self.path = DEFAULT_DIARY_DIR / SPEAKERS_FILE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    def find_person(self, name: str) -> Person | None:
        key = name.strip().lower()
        for p in self.people:
            if p.name.lower() == key:
                return p
        return None

    def add_person(self, name: str) -> Person:
        name = name.strip()
        if not name:
            raise ValueError("Person name cannot be empty")
        existing = self.find_person(name)
        if existing:
            return existing
        person = Person(
            id=f"p_{uuid.uuid4().hex[:8]}",
            name=name,
            created_at=datetime.now().isoformat(timespec="seconds"),
            use_count=0,
        )
        self.people.append(person)
        self.save()
        return person

    def rename_person(self, old_name: str, new_name: str) -> Person:
        person = self.find_person(old_name)
        if not person:
            raise ValueError(f"Unknown person: {old_name}")
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("New name cannot be empty")
        # update global defaults that pointed at old name
        for k, v in list(self.global_defaults.items()):
            if v == person.name:
                self.global_defaults[k] = new_name
        for k, v in list(self.recent_by_label.items()):
            if v == person.name:
                self.recent_by_label[k] = new_name
        person.name = new_name
        self.save()
        return person

    def remove_person(self, name: str) -> bool:
        person = self.find_person(name)
        if not person:
            return False
        self.people = [p for p in self.people if p.id != person.id]
        self.global_defaults = {k: v for k, v in self.global_defaults.items() if v != person.name}
        self.recent_by_label = {k: v for k, v in self.recent_by_label.items() if v != person.name}
        self.save()
        return True

    def bump_use(self, name: str) -> None:
        person = self.find_person(name)
        if person:
            person.use_count += 1
            self.save()

    def remember_defaults(self, mapping: dict[str, str]) -> None:
        """Persist label→name as global defaults for future sessions."""
        for raw, name in mapping.items():
            raw = normalize_label(raw)
            name = name.strip()
            if not raw or not name:
                continue
            self.global_defaults[raw] = name
            self.recent_by_label[raw] = name
            self.add_person(name)
            self.bump_use(name)
        self.save()

    def suggested_map(self, raw_labels: list[str]) -> dict[str, str]:
        """Suggest names for raw labels using recent + global defaults."""
        out: dict[str, str] = {}
        for raw in raw_labels:
            key = normalize_label(raw)
            if key in self.recent_by_label:
                out[raw] = self.recent_by_label[key]
            elif key in self.global_defaults:
                out[raw] = self.global_defaults[key]
            elif raw in self.global_defaults:
                out[raw] = self.global_defaults[raw]
        return out


def normalize_label(label: str) -> str:
    """Normalize Speaker 1 / S01 / [S01] to a canonical key."""
    s = str(label).strip()
    m = re.fullmatch(r"\[?S0*(\d+)\]?", s, flags=re.IGNORECASE)
    if m:
        return f"Speaker {int(m.group(1))}"
    m = re.fullmatch(r"Speaker\s*0*(\d+)", s, flags=re.IGNORECASE)
    if m:
        return f"Speaker {int(m.group(1))}"
    return s


def parse_rename_pairs(pairs: list[str]) -> dict[str, str]:
    """Parse CLI pairs like 'Speaker 1=Alex' or 'S01:Me'."""
    mapping: dict[str, str] = {}
    for item in pairs:
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            left, right = item.split("=", 1)
        elif ":" in item:
            left, right = item.split(":", 1)
        else:
            raise ValueError(f"Expected LABEL=Name, got: {item}")
        left, right = left.strip(), right.strip()
        if not left or not right:
            raise ValueError(f"Invalid rename pair: {item}")
        mapping[normalize_label(left)] = right
    return mapping


def raw_labels_from_transcript_data(data: dict) -> list[str]:
    if "transcript" in data and isinstance(data["transcript"], dict):
        segs = data["transcript"].get("segments", [])
    else:
        segs = data.get("segments", [])
    labels: list[str] = []
    for seg in segs or []:
        if not isinstance(seg, dict):
            continue
        sp = seg.get("speaker")
        if sp and sp not in labels:
            labels.append(str(sp))
    return labels


def resolve_display_map(
    raw_labels: list[str],
    *,
    entry_map: dict[str, str] | None = None,
    store: SpeakerStore | None = None,
) -> dict[str, str]:
    """
    Build raw_label → display name for rendering.

    Priority: entry_map (exact + normalized) → store suggestions → original label.
    """
    store = store or SpeakerStore.load()
    entry_map = entry_map or {}
    # normalize entry map keys
    norm_entry = {normalize_label(k): v for k, v in entry_map.items()}
    # also allow raw keys
    for k, v in entry_map.items():
        if k not in norm_entry:
            norm_entry[k] = v

    suggestions = store.suggested_map(raw_labels)
    out: dict[str, str] = {}
    for raw in raw_labels:
        key = normalize_label(raw)
        if raw in entry_map:
            out[raw] = entry_map[raw]
        elif key in norm_entry:
            out[raw] = norm_entry[key]
        elif raw in suggestions:
            out[raw] = suggestions[raw]
        elif key in suggestions:
            out[raw] = suggestions[key]
        else:
            out[raw] = raw
    return out


def apply_map_to_segments(segments: list[dict], display_map: dict[str, str]) -> list[dict]:
    """Return new segment dicts with speaker display names (keeps original_speaker)."""
    out = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        new_seg = dict(seg)
        raw = str(seg.get("speaker") or "?")
        key = normalize_label(raw)
        display = display_map.get(raw) or display_map.get(key) or raw
        new_seg["original_speaker"] = seg.get("original_speaker") or raw
        new_seg["speaker"] = display
        out.append(new_seg)
    return out


def get_entry_speaker_map(entry: DiaryEntry, diary_dir: Path | None = None) -> dict[str, str]:
    """Load speaker_map from entry index file and/or transcript meta."""
    mapping: dict[str, str] = {}
    root = Path(diary_dir) if diary_dir else DEFAULT_DIARY_DIR

    entry_path = root / "entries" / f"{entry.id}.json"
    if entry_path.exists():
        try:
            data = json.loads(entry_path.read_text(encoding="utf-8"))
            sm = data.get("speaker_map") or {}
            if isinstance(sm, dict):
                mapping.update({str(k): str(v) for k, v in sm.items()})
        except Exception:
            pass

    # Also attribute on DiaryEntry if present
    sm_attr = getattr(entry, "speaker_map", None)
    if isinstance(sm_attr, dict):
        mapping.update({str(k): str(v) for k, v in sm_attr.items()})

    data = load_transcript_data(entry)
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    sm = meta.get("speaker_map") or {}
    if isinstance(sm, dict):
        mapping.update({str(k): str(v) for k, v in sm.items()})

    return mapping


def set_entry_speaker_map(
    entry_id: str,
    mapping: dict[str, str],
    *,
    diary_dir: Path | None = None,
    remember: bool = False,
    merge: bool = True,
) -> dict[str, str]:
    """
    Persist speaker renames for an entry.

    Updates entries/<id>.json and transcript meta.speaker_map.
    If remember=True, also updates global defaults / roster.
    """
    root = Path(diary_dir) if diary_dir else DEFAULT_DIARY_DIR
    entry = get_entry(entry_id, root)
    if not entry:
        raise ValueError(f"Entry not found: {entry_id}")

    # Normalize keys
    clean = {normalize_label(k): v.strip() for k, v in mapping.items() if v and str(v).strip()}
    if merge:
        existing = get_entry_speaker_map(entry, root)
        existing_norm = {normalize_label(k): v for k, v in existing.items()}
        existing_norm.update(clean)
        clean = existing_norm

    # Update entry index
    entries_dir = root / "entries"
    entries_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entries_dir / f"{entry.id}.json"
    if entry_path.exists():
        try:
            edata = json.loads(entry_path.read_text(encoding="utf-8"))
        except Exception:
            edata = entry.to_dict()
    else:
        edata = entry.to_dict()

    edata["speaker_map"] = clean
    # Always derive raw labels from transcript segments (not display names)
    raw_labels: list[str] = []
    if entry.transcript_path:
        raw_labels = raw_labels_from_transcript_data(load_transcript_data(entry))
    if not raw_labels:
        raw_labels = list(clean.keys())
    display_map = resolve_display_map(raw_labels, entry_map=clean)
    edata["speakers"] = [display_map.get(s, s) for s in raw_labels] or list(clean.values())
    edata["raw_speakers"] = raw_labels
    entry_path.write_text(json.dumps(edata, indent=2), encoding="utf-8")

    # Update transcript meta
    if entry.transcript_path and Path(entry.transcript_path).exists():
        tpath = Path(entry.transcript_path)
        try:
            tdata = json.loads(tpath.read_text(encoding="utf-8"))
        except Exception:
            tdata = {}
        meta = tdata.get("meta") if isinstance(tdata.get("meta"), dict) else {}
        meta = dict(meta)
        meta["speaker_map"] = clean
        tdata["meta"] = meta
        tpath.write_text(json.dumps(tdata, indent=2), encoding="utf-8")

    store = SpeakerStore.load(root)
    for raw, name in clean.items():
        store.add_person(name)
        store.recent_by_label[normalize_label(raw)] = name
        store.bump_use(name)
    if remember:
        store.remember_defaults(clean)
    else:
        store.save()

    return clean


def display_speakers_for_entry(
    entry: DiaryEntry,
    *,
    diary_dir: Path | None = None,
    store: SpeakerStore | None = None,
) -> list[str]:
    store = store or SpeakerStore.load(diary_dir)
    entry_map = get_entry_speaker_map(entry, diary_dir)
    # Prefer labels from transcript (anonymous), not already-renamed entry.speakers
    raw: list[str] = []
    if entry.has_transcript:
        raw = raw_labels_from_transcript_data(load_transcript_data(entry))
    if not raw:
        raw = list(entry_map.keys()) or (entry.speakers or [])
    dmap = resolve_display_map(raw, entry_map=entry_map, store=store)
    seen = set()
    out = []
    for r in raw:
        name = dmap.get(r, r)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def filter_entries_by_person(
    person: str,
    *,
    diary_dir: Path | None = None,
    limit: int | None = 100,
) -> list[DiaryEntry]:
    """Return entries where this person appears (raw label or renamed name)."""
    root = Path(diary_dir) if diary_dir else DEFAULT_DIARY_DIR
    store = SpeakerStore.load(root)
    key = person.strip().lower()
    results: list[DiaryEntry] = []

    for entry in list_entries(root, limit=None):
        names = [s.lower() for s in display_speakers_for_entry(entry, diary_dir=root, store=store)]
        raw = [s.lower() for s in (entry.speakers or [])]
        entry_map = get_entry_speaker_map(entry, root)
        mapped_vals = [v.lower() for v in entry_map.values()]
        if key in names or key in raw or key in mapped_vals:
            results.append(entry)
            continue
        # also search transcript body labels after mapping
        if entry.has_transcript:
            data = load_transcript_data(entry)
            labels = raw_labels_from_transcript_data(data)
            dmap = resolve_display_map(labels, entry_map=entry_map, store=store)
            if any(key == v.lower() or key == k.lower() for k, v in dmap.items()):
                results.append(entry)

    results.sort(key=lambda e: e.created_ts, reverse=True)
    if limit is not None:
        results = results[:limit]
    return results


def format_transcript_with_names(
    data: dict,
    *,
    entry_map: dict[str, str] | None = None,
    store: SpeakerStore | None = None,
) -> str:
    """Format transcript text applying speaker display names."""
    if "transcript" in data and isinstance(data["transcript"], dict):
        segs = data["transcript"].get("segments", [])
    else:
        segs = data.get("segments", [])
    if not isinstance(segs, list):
        segs = []

    raw_labels = raw_labels_from_transcript_data(data)
    dmap = resolve_display_map(raw_labels, entry_map=entry_map, store=store)
    lines = []
    for seg in segs:
        if not isinstance(seg, dict):
            continue
        raw = str(seg.get("speaker") or "?")
        sp = dmap.get(raw) or dmap.get(normalize_label(raw)) or raw
        start = seg.get("start", seg.get("start_time", 0))
        end = seg.get("end", seg.get("end_time", 0))
        text = seg.get("text", "")
        try:
            lines.append(f"[{sp}] ({float(start):.1f}s - {float(end):.1f}s): {text}")
        except (TypeError, ValueError):
            lines.append(f"[{sp}]: {text}")
    return "\n".join(lines)


def roster_for_api(diary_dir: Path | None = None) -> dict[str, Any]:
    store = SpeakerStore.load(diary_dir)
    return {
        "people": [p.to_dict() for p in sorted(store.people, key=lambda p: (-p.use_count, p.name.lower()))],
        "global_defaults": store.global_defaults,
        "recent_by_label": store.recent_by_label,
    }
