"""Simplified harness for Streamlit – prompts, memories, skills, subagents, refinements."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

Kind = Literal["prompt", "memory", "skill", "subagent"]
Scope = Literal["local", "global"]

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _normalize_id(title: str, kind: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    cleaned = cleaned[:80] or kind
    return cleaned

@dataclass
class HarnessEntry:
    id: str
    kind: Kind
    title: str
    content: str
    path: str = "general"
    scope: Scope = "local"
    reference: Dict[str, Any] = field(default_factory=dict)
    arguments: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    source: str = "agent"
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    version: int = 1

@dataclass
class RefinementEvent:
    id: str
    trigger: str
    changes: List[str]
    evidence: Optional[str] = None
    outcome: Optional[str] = None
    created_at: str = field(default_factory=_utc_now)

class HarnessState:
    def __init__(self, state_file: Path, scope: Scope = "local"):
        self.state_file = state_file
        self.scope = scope
        self.entries: Dict[Kind, Dict[str, HarnessEntry]] = {
            "prompt": {}, "memory": {}, "skill": {}, "subagent": {}
        }
        self.refinements: List[RefinementEvent] = []
        self._mtime: Optional[float] = None
        self.load()

    def load(self) -> None:
        if not self.state_file.exists():
            self.save()
            return
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            for kind in self.entries:
                raw = data.get("entries", {}).get(kind, {})
                if not isinstance(raw, dict):
                    continue
                for eid, rec in raw.items():
                    try:
                        self.entries[kind][eid] = HarnessEntry(**{
                            k: v for k, v in rec.items()
                            if k in HarnessEntry.__dataclass_fields__
                        })
                    except Exception:
                        continue
            self.refinements = []
            for r in data.get("refinements", []):
                try:
                    self.refinements.append(RefinementEvent(**{
                        k: v for k, v in r.items()
                        if k in RefinementEvent.__dataclass_fields__
                    }))
                except Exception:
                    continue
            self._mtime = self.state_file.stat().st_mtime
        except Exception:
            # corrupt → empty
            pass

    def save(self) -> None:
        payload = {
            "schema": 1,
            "entries": {
                kind: {eid: asdict(e) for eid, e in ents.items()}
                for kind, ents in self.entries.items()
            },
            "refinements": [asdict(r) for r in self.refinements],
        }
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._mtime = self.state_file.stat().st_mtime

    def _check_external(self) -> None:
        if self.state_file.exists() and self._mtime is not None:
            if self.state_file.stat().st_mtime > self._mtime:
                self.load()

    def create(
        self,
        kind: Kind,
        title: str,
        content: str,
        path: str = "general",
        reference: Optional[Dict] = None,
        arguments: Optional[Dict] = None,
        metadata: Optional[Dict] = None,
    ) -> HarnessEntry:
        self._check_external()
        eid = _normalize_id(title, kind)
        if eid in self.entries[kind]:
            raise ValueError(f"{kind} id '{eid}' already exists")
        entry = HarnessEntry(
            id=eid,
            kind=kind,
            title=title,
            content=content,
            path=path,
            scope=self.scope,
            reference=reference or {},
            arguments=arguments or {},
            metadata=metadata or {},
        )
        self.entries[kind][eid] = entry
        self.save()
        return entry

    def upsert(self, kind: Kind, title: str, content: str, **kwargs) -> HarnessEntry:
        self._check_external()
        eid = _normalize_id(title, kind)
        if eid in self.entries[kind]:
            return self.update(kind, eid, title=title, content=content, **kwargs)
        return self.create(kind, title, content, **kwargs)

    def update(
        self,
        kind: Kind,
        eid: str,
        title: Optional[str] = None,
        content: Optional[str] = None,
        path: Optional[str] = None,
        reference: Optional[Dict] = None,
        arguments: Optional[Dict] = None,
        metadata: Optional[Dict] = None,
    ) -> HarnessEntry:
        self._check_external()
        if eid not in self.entries[kind]:
            raise KeyError(f"{kind} '{eid}' not found")
        e = self.entries[kind][eid]
        if title is not None:
            e.title = title
        if content is not None:
            e.content = content
        if path is not None:
            e.path = path
        if reference is not None:
            e.reference = reference
        if arguments is not None:
            e.arguments = arguments
        if metadata is not None:
            e.metadata = metadata
        e.updated_at = _utc_now()
        e.version += 1
        self.save()
        return e

    def delete(self, kind: Kind, eid: str) -> bool:
        self._check_external()
        if eid in self.entries[kind]:
            del self.entries[kind][eid]
            self.save()
            return True
        return False

    def get(self, kind: Kind, eid: str) -> Optional[HarnessEntry]:
        self._check_external()
        return self.entries[kind].get(eid)

    def list(self, kind: Optional[Kind] = None) -> List[HarnessEntry]:
        self._check_external()
        items: List[HarnessEntry] = []
        kinds = [kind] if kind else list(self.entries.keys())
        for k in kinds:
            items.extend(self.entries[k].values())
        items.sort(key=lambda e: (e.kind, e.path, e.title, e.id))
        return items

    def record_refinement(
        self,
        trigger: str,
        changes: List[str],
        evidence: Optional[str] = None,
        outcome: Optional[str] = None,
    ) -> RefinementEvent:
        self._check_external()
        rid = f"ref_{len(self.refinements) + 1:04d}"
        ev = RefinementEvent(id=rid, trigger=trigger, changes=changes,
                             evidence=evidence, outcome=outcome)
        self.refinements.append(ev)
        self.save()
        return ev

    def overview(self) -> str:
        lines = [f"Harness scope={self.scope}  file={self.state_file}"]
        for kind in self.entries:
            ents = self.entries[kind]
            lines.append(f"\n## {kind} ({len(ents)})")
            for e in sorted(ents.values(), key=lambda x: x.title):
                lines.append(f"  • {e.id}  –  {e.title}  (v{e.version})")
        if self.refinements:
            lines.append(f"\n## refinements ({len(self.refinements)})")
            for r in self.refinements[-5:]:
                lines.append(f"  • {r.id}: {r.trigger}")
        return "\n".join(lines)

def get_harness(state_dir: Optional[Path] = None, global_: bool = False) -> HarnessState:
    if state_dir is None:
        state_dir = Path(".")
    name = "harness_state_global.json" if global_ else "harness_state.json"
    return HarnessState(state_dir / name, scope="global" if global_ else "local")
