"""Commissioning: take a request from "someone asked" to "it has a home and is being tracked".

The steps follow the network registry's TRIAGE.md. This module does the bookkeeping between
nodes so the owner does not have to carry messages by hand:

  check     read-only: is it already in the registry, is there a capability, what lessons apply
  open      record the request; attach it to an existing entry or write a new `caught` entry
  decide    record the owner's triage outcome on the entry; for `seed`, the incubator's
            init-seed script creates the repository and sets the entry's home
  progress  in progress, blocked or done, with a note and a reference

A commission is a JSON file under <data dir>/commissions/. The registry entry is the durable
record; each change to it is committed there on its own, never pushed. Decisions belong to the
owner: `decide` records who made one and never makes one itself.
"""
from __future__ import annotations

import datetime
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from . import network_registry

OUTCOMES = ("idea", "seed", "routed", "adopted", "parked", "set-aside")
# triage: an agent is preparing the case. awaiting-decision: a recommendation and a question exist, so it is the
# owner's turn. Only that state belongs in the owner's queue.
STATES = ("triage", "awaiting-decision", "decided", "in-progress", "blocked", "done", "withdrawn")
KINDS = ("product", "tool", "library", "skill", "research", "issue", "capability")
CATEGORIES = ("products", "shared", "devnet", "research")
PLAYBOOK = "idea-triage"
STOP = set("a an and are as at be but by can do does for from has have if in into is it its no not of on or so "
           "than that the their there this to too was when which while with without we need want should".split())


class CommissionError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _today() -> str:
    return datetime.date.today().isoformat()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tokens(text: Any) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-z0-9]+", str(text).lower()) if w not in STOP and len(w) > 2}


def _text(value: Any, name: str, maximum: int, required: bool = True) -> str:
    if (value is None or value == "") and not required:
        return ""
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise CommissionError(f"{name} must be text of 1 to {maximum} characters")
    return value.strip()


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48].strip("-")
    if not slug:
        raise CommissionError("title needs at least one letter or digit")
    return slug


class Commissioning:
    def __init__(self, registry_root: Path, data_dir: Path, factory_root: Path, network_root: Path,
                 capability_check: Callable[[str], dict[str, Any]] | None = None,
                 lessons: Callable[[str, str, str], dict[str, Any]] | None = None,
                 brief_lookup: Callable[[str], dict[str, Any]] | None = None) -> None:
        self.registry_root = Path(registry_root)
        self.folder = Path(data_dir) / "commissions"
        self.factory_root, self.network_root = Path(factory_root), Path(network_root)
        self.capability_check, self.lessons, self.brief_lookup = capability_check, lessons, brief_lookup

    # ---- registry writes -----------------------------------------------------------------
    def _entry_path(self, entry_id: str) -> Path:
        if not isinstance(entry_id, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}-[a-z0-9]+(-[a-z0-9]+)*", entry_id):
            raise CommissionError("registry entry ids look like YYYY-MM-DD-slug")
        return self.registry_root / "entries" / f"{entry_id}.json"

    def _entry(self, entry_id: str) -> dict[str, Any]:
        path = self._entry_path(entry_id)
        if not path.is_file():
            raise CommissionError(f"no registry entry {entry_id}", 404)
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_entry(self, entry: dict[str, Any], message: str) -> None:
        path = self._entry_path(entry["id"])
        path.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        if (self.registry_root / ".git").exists():
            rel = path.relative_to(self.registry_root).as_posix()
            for args in (["add", "--", rel], ["commit", "--quiet", "-m", message, "--", rel]):
                done = subprocess.run(["git", *args], cwd=self.registry_root, capture_output=True, text=True,
                                      stdin=subprocess.DEVNULL)
                if done.returncode != 0 and "nothing to commit" not in done.stdout + done.stderr:
                    raise CommissionError(f"registry commit failed: {done.stderr.strip() or done.stdout.strip()}", 503)

    # ---- commission records --------------------------------------------------------------
    def _path(self, commission_id: str) -> Path:
        if not isinstance(commission_id, str) or not re.fullmatch(r"COM-\d{8}-[a-z0-9-]{1,60}", commission_id):
            raise CommissionError("commission ids look like COM-YYYYMMDD-slug")
        return self.folder / f"{commission_id}.json"

    def get(self, commission_id: str) -> dict[str, Any]:
        path = self._path(commission_id)
        if not path.is_file():
            raise CommissionError(f"no commission {commission_id}", 404)
        record = json.loads(path.read_text(encoding="utf-8"))
        try:
            entry = self._entry(record["entry_id"])
            record["entry"] = {k: entry.get(k) for k in ("id", "title", "status", "home", "decision")}
        except CommissionError:
            record["entry"] = None
        return record

    def _save(self, record: dict[str, Any], event: str, detail: dict[str, Any]) -> dict[str, Any]:
        record.pop("entry", None)
        record["history"].append({"at": _now(), "event": event, **detail})
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self._path(record["id"])
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)
        return self.get(record["id"])

    def list(self, state: str = "") -> dict[str, Any]:
        if state and state not in STATES:
            raise CommissionError(f"state must be one of: {', '.join(STATES)}")
        items = []
        for path in sorted(self.folder.glob("COM-*.json")) if self.folder.is_dir() else []:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not state or record["state"] == state:
                items.append({k: record[k] for k in ("id", "title", "state", "entry_id", "requested_by", "opened")}
                             | {"next": record["next"]})
        return {"count": len(items), "commissions": items}

    # ---- steps ---------------------------------------------------------------------------
    def check(self, title: str, need: str, repo: str = "") -> dict[str, Any]:
        """Read-only. What the network already has that bears on this request."""
        title, need = _text(title, "title", 200), _text(need, "need", 4000)
        wanted = _tokens(title + " " + need)
        loaded = network_registry.load_entries(self.registry_root)
        candidates = []
        for entry in loaded["entries"]:
            score = len(wanted & _tokens(f"{entry['title']} {entry.get('origin', '')} {entry.get('core', '')}"))
            score += 3 * len(_tokens(title) & _tokens(entry["title"]))
            if score >= 3:
                candidates.append({"id": entry["id"], "title": entry["title"], "status": entry["status"],
                                   "home": entry["home"], "kind": entry["kind"], "score": score})
        candidates.sort(key=lambda c: (-c["score"], c["id"]))
        result: dict[str, Any] = {
            "registry": {"candidates": candidates[:6], "searched": len(loaded["entries"]),
                         "note": "Shared words only. A missing match does not prove it is new; read the candidates."},
            "playbook": {"name": PLAYBOOK, "why": "Opens the request up and recommends one outcome for the owner to decide.",
                         "rules": str(self.registry_root / "TRIAGE.md")},
        }
        for name, call in (("capabilities", lambda: self.capability_check(f"{title}. {need}"[:2000]) if self.capability_check else None),
                           ("lessons", lambda: self.lessons(f"{title}. {need}"[:2000], repo, "before-building") if self.lessons else None)):
            try:
                value = call()
                result[name] = value if value is not None else {"unavailable": "not configured"}
            except Exception as exc:  # a check that fails must not hide the others
                result[name] = {"unavailable": str(exc)[:300]}
        return result

    def open(self, title: str, need: str, requested_by: str, source_repo: str = "", kind: str = "capability",
             existing_entry: str = "") -> dict[str, Any]:
        title, need = _text(title, "title", 200), _text(need, "need", 4000)
        requested_by = _text(requested_by, "requested_by", 200)
        source_repo = _text(source_repo, "source_repo", 300, required=False)
        if kind not in KINDS:
            raise CommissionError(f"kind must be one of: {', '.join(KINDS)}")
        commission_id = f"COM-{_today().replace('-', '')}-{_slug(title)}"
        if self._path(commission_id).exists():
            raise CommissionError(f"{commission_id} is already open; use progress or pick a different title", 409)
        checked = self.check(title, need, source_repo)
        if existing_entry:
            entry = self._entry(existing_entry)
            refs = entry.setdefault("refs", [])
            if f"commission:{commission_id}" not in refs:
                refs.append(f"commission:{commission_id}")
            self._save_entry(entry, f"Attach {commission_id} to {entry['id']}")
            attached = True
        else:
            exact = [c for c in checked["registry"]["candidates"] if c["title"].strip().lower() == title.lower()]
            entry_id = f"{_today()}-{_slug(title)}"
            if exact or self._entry_path(entry_id).exists() or list((self.registry_root / "entries").glob(f"*-{_slug(title)}.json")):
                raise CommissionError("the registry already has an entry with this name; pass existing_entry to attach to it", 409)
            entry = {"id": entry_id, "kind": kind, "title": title, "status": "caught", "home": None,
                     "initialized_by": "control-plane", "initialized_on": _today(),
                     "origin": f"{need} Requested by {requested_by}" + (f" from {source_repo}." if source_repo else "."),
                     "refs": [f"commission:{commission_id}"]}
            self._save_entry(entry, f"Catch {entry_id} ({commission_id})")
            attached = False
        waiting = entry["status"] in ("caught", "idea")
        # Nothing reaches the owner's queue until triage has produced a recommendation and a question.
        record = {"id": commission_id, "title": title, "need": need, "requested_by": requested_by,
                  "source_repo": source_repo, "opened": _now(), "entry_id": entry["id"], "attached_to_existing": attached,
                  "state": "triage" if waiting else "decided", "check": checked, "history": [],
                  "next": (f"Run the {PLAYBOOK} playbook on {entry['id']} and call recommend with the outcome you advise, "
                           f"your sourced reasoning and the question for the owner. It reaches the owner's queue only then."
                           if waiting else f"{entry['id']} is already '{entry['status']}' at {entry['home']}; report progress there.")}
        return self._save(record, "opened", {"by": requested_by, "attached": attached})

    def note(self, entry_id: str, text: str, by: str, source: str = "") -> dict[str, Any]:
        """Something said in passing. Recorded against the entry; no commission, nothing queued for anyone."""
        entry = self._entry(entry_id)
        notes = entry.setdefault("notes", [])
        notes.append({"date": _today(), "by": _text(by, "by", 200), "text": _text(text, "text", 2000),
                      **({"source": _text(source, "source", 500)} if source else {})})
        self._save_entry(entry, f"Note on {entry['id']}")
        return {"entry": entry["id"], "notes": len(notes), "queued_for_owner": False,
                "next": "Nothing is asked of the owner. Commission it only when they ask for work on it."}

    def recommend(self, commission_id: str, outcome: str, reasoning: str, question: str, by: str,
                  sources: list[dict[str, str]] | None = None, alternatives: str = "", brief: str = "") -> dict[str, Any]:
        """Triage's product: an advised outcome, its reasoning with sources, and the one question for the owner."""
        record = self.get(commission_id)
        if record["state"] not in ("triage", "awaiting-decision"):
            raise CommissionError(f"{commission_id} is '{record['state']}'; only a commission in triage takes a recommendation", 409)
        if outcome not in OUTCOMES:
            raise CommissionError(f"outcome must be one of: {', '.join(OUTCOMES)}")
        if not sources and not brief:
            raise CommissionError("a recommendation needs its sources (ref and what each says) or a stored decision brief; "
                                  "the owner is not asked to choose between unsourced options", 400)
        if brief and self.brief_lookup is not None:
            found = self.brief_lookup(brief)
            if not isinstance(found, dict) or found.get("unavailable") or found.get("error"):
                raise CommissionError(f"brief {brief} could not be read: {found.get('unavailable') or found.get('error') if isinstance(found, dict) else found}", 404)
        clean = []
        for item in sources or []:
            if not isinstance(item, dict) or not item.get("ref") or not item.get("says"):
                raise CommissionError("each source needs ref and says (what it says that bears on this)")
            clean.append({"ref": _text(item["ref"], "source ref", 500), "says": _text(item["says"], "source says", 600),
                          "checked": item.get("checked") or _today()})
        record["state"] = "awaiting-decision"
        record["recommendation"] = {"outcome": outcome, "reasoning": _text(reasoning, "reasoning", 4000),
                                    "question": _text(question, "question", 600), "sources": clean,
                                    "alternatives": _text(alternatives, "alternatives", 2000, required=False),
                                    **({"brief": _text(brief, "brief", 80)} if brief else {})}
        record["next"] = f"Owner: {record['recommendation']['question']}"
        return self._save(record, "recommended", {"by": _text(by, "by", 200), "outcome": outcome})

    def withdraw(self, commission_id: str, reason: str, by: str) -> dict[str, Any]:
        """Take back a commission opened by mistake. The entry and its history stay; only the request goes."""
        record = self.get(commission_id)
        untouched = record["state"] == "decided" and all(h["event"] == "opened" for h in record["history"])
        if record["state"] not in ("triage", "awaiting-decision") and not untouched:
            raise CommissionError(f"{commission_id} is '{record['state']}'; only an undecided or untouched commission can be withdrawn", 409)
        entry = self._entry(record["entry_id"])
        ref = f"commission:{commission_id}"
        if ref in entry.get("refs", []):
            entry["refs"].remove(ref)
        if record["attached_to_existing"]:
            self._save_entry(entry, f"Withdraw {commission_id} from {entry['id']}")
        else:
            entry.setdefault("notes", []).append({"date": _today(), "by": by, "text": f"Withdrawn request: {reason}"})
            self._save_entry(entry, f"Withdraw {commission_id}; {entry['id']} stays as caught")
        record["state"] = "withdrawn"
        record["next"] = "Withdrawn. Nothing is asked of the owner."
        return self._save(record, "withdrawn", {"by": _text(by, "by", 200), "reason": _text(reason, "reason", 1000)})

    def decide(self, commission_id: str, outcome: str, reason: str, decided_by: str, home: str = "",
               prior_art: str = "", name: str = "", category: str = "", core: str = "", quote: str = "") -> dict[str, Any]:
        record = self.get(commission_id)
        if outcome not in OUTCOMES:
            raise CommissionError(f"outcome must be one of: {', '.join(OUTCOMES)}")
        reason, decided_by = _text(reason, "reason", 2000), _text(decided_by, "decided_by", 200)
        # Who is speaking cannot be verified here, so a decision is the caller's record of what the owner said:
        # their words are required and shown wherever the decision appears, and it is marked unverified.
        quote = _text(quote, "quote (the owner's own words giving this decision)", 1000)
        entry = self._entry(record["entry_id"])
        if entry["status"] not in ("caught", "idea", "parked", "set-aside"):
            raise CommissionError(f"{entry['id']} is already '{entry['status']}'; nothing to decide", 409)
        entry["decision"] = {"date": _today(), "reason": reason, "decided_by": decided_by, "quote": quote, "verified": False}
        if core:
            entry["core"] = _text(core, "core", 600)
        seeded = None
        if outcome in ("routed", "adopted"):
            entry["home"] = _text(home, "home (where it goes or what is adopted)", 500)
            entry["status"] = outcome
        elif outcome == "seed":
            entry["prior_art"] = _text(prior_art, "prior_art (what was searched, what exists, why build)", 4000)
            name = _text(name, "name (folder name for the new repository)", 64)
            if category not in CATEGORIES:
                raise CommissionError(f"category must be one of: {', '.join(CATEGORIES)}")
            self._save_entry(entry, f"Record seed decision on {entry['id']} ({commission_id})")
            seeded = self._init_seed(entry, name, category)
            entry = self._entry(entry["id"])
        else:
            entry["status"] = outcome
        if outcome != "seed":
            self._save_entry(entry, f"Decide {entry['id']}: {outcome} ({commission_id})")
        record["state"] = "decided"
        record["next"] = {
            "seed": f"Build in {entry['home']}; report progress with commission progress.",
            "routed": f"Do the work in {entry['home']}; report progress with commission progress.",
            "adopted": f"Set up {entry['home']}; report progress with commission progress.",
        }.get(outcome, f"Nothing to build now ({outcome}). Reopen by deciding again when that changes.")
        return self._save(record, "decided", {"outcome": outcome, "reason": reason, "decided_by": decided_by, "quote": quote,
                                             "verified": False,
                                             **({"seeded": seeded} if seeded else {})})

    def _init_seed(self, entry: dict[str, Any], name: str, category: str) -> dict[str, Any]:
        script = self.factory_root / ".github" / "skills" / "init-seed" / "scripts" / "init_seed.py"
        if not script.is_file():
            raise CommissionError(f"the incubator's init-seed script is not at {script}", 503)
        done = subprocess.run(
            [sys.executable, str(script), name, "--title", entry["title"], "--origin", entry["origin"],
             "--category", category, "--entry", entry["id"],
             "--network-root", str(self.network_root), "--registry-root", str(self.registry_root)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
        if done.returncode != 0:
            raise CommissionError(f"init-seed refused: {(done.stderr or done.stdout).strip()[:500]}", 409)
        return {"created": json.loads(done.stdout).get("created")}

    def progress(self, commission_id: str, state: str, note: str, by: str, ref: str = "") -> dict[str, Any]:
        record = self.get(commission_id)
        if state not in ("in-progress", "blocked", "done"):
            raise CommissionError("state must be in-progress, blocked or done")
        note, by = _text(note, "note", 2000), _text(by, "by", 200)
        ref = _text(ref, "ref", 500, required=False)
        if record["state"] in ("triage", "awaiting-decision"):
            raise CommissionError("the owner has not decided this one yet; record the decision first", 409)
        if record["state"] == "withdrawn":
            raise CommissionError("this commission was withdrawn", 409)
        entry = self._entry(record["entry_id"])
        if state == "in-progress" and entry["status"] == "seed":
            entry["status"] = "growing"
            self._save_entry(entry, f"{entry['id']} is growing ({commission_id})")
        if state == "done" and ref:
            refs = entry.setdefault("refs", [])
            if ref not in refs:
                refs.append(ref)
                self._save_entry(entry, f"Record completion evidence on {entry['id']} ({commission_id})")
        record["state"] = state
        record["next"] = {"in-progress": "Report blocked or done when it changes.",
                          "blocked": "Needs the blocker cleared; say who can clear it in the note.",
                          "done": "Reported done by the worker. The owner accepts or reopens; this is not acceptance."}[state]
        return self._save(record, state, {"note": note, "by": by, **({"ref": ref} if ref else {})})
