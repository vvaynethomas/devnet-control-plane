"""Pillar 5: Interaction Engineering (InteractionFrame Registry, Compiler, and Side-by-Side Lab Bench)."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
import sqlite3
import time
import urllib.request
from pathlib import Path
from typing import Any

from . import DEFAULT_DATA_DIR, REGISTRY_PATH


def _canonical_digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


class InteractionFrameEngine:
    """Manages versioned InteractionFrames, compiles framed prompts, and persists side-by-side evaluations."""

    def __init__(
        self,
        registry_path: Path = REGISTRY_PATH,
        db_path: Path | None = None,
    ) -> None:
        self.registry_path = registry_path
        self.db_path = db_path or (DEFAULT_DATA_DIR / "interaction_lab.sqlite")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS custom_frames (
                    id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    presentation TEXT NOT NULL,
                    user_model TEXT NOT NULL,
                    assistant_model TEXT NOT NULL,
                    relationship TEXT NOT NULL,
                    desired_behaviors_json TEXT NOT NULL,
                    content_digest TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evaluation_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    task_prompt TEXT NOT NULL,
                    desired_behavior TEXT NOT NULL,
                    execution_mode TEXT NOT NULL,
                    baseline_frame_id TEXT NOT NULL,
                    variants_json TEXT NOT NULL,
                    notes TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def load_registry(self) -> dict[str, Any]:
        base = json.loads(self.registry_path.read_text(encoding="utf-8"))
        affects = {a["id"]: {**a, "digest": _canonical_digest(a)} for a in base.get("affects", [])}
        user_models = {u["id"]: {**u, "digest": _canonical_digest(u)} for u in base.get("user_models", [])}
        assistant_models = {
            m["id"]: {**m, "digest": _canonical_digest(m)} for m in base.get("assistant_models", [])
        }
        relationships = {
            r["id"]: {**r, "digest": _canonical_digest(r)} for r in base.get("relationships", [])
        }

        frames: list[dict[str, Any]] = []
        for f in base.get("frames", []):
            frames.append({**f, "source": "seed", "digest": _canonical_digest(f)})

        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM custom_frames ORDER BY created_at DESC").fetchall()
            for r in rows:
                frames.append(
                    {
                        "id": r["id"],
                        "version": r["version"],
                        "title": r["title"],
                        "description": r["description"],
                        "presentation": r["presentation"],
                        "user_model": r["user_model"],
                        "assistant_model": r["assistant_model"],
                        "relationship": r["relationship"],
                        "desired_behaviors": json.loads(r["desired_behaviors_json"]),
                        "digest": r["content_digest"],
                        "source": "user-created",
                    }
                )

        return {
            "schema_version": base.get("schema_version", "1.0.0"),
            "origin_ref": base.get("origin_ref", "SRC-0016"),
            "affects": affects,
            "user_models": user_models,
            "assistant_models": assistant_models,
            "relationships": relationships,
            "frames": frames,
            "frames_by_id": {f["id"]: f for f in frames},
            "benchmark_tasks": base.get("benchmark_tasks", []),
        }

    def save_custom_frame(
        self,
        frame_id: str,
        title: str,
        description: str,
        presentation: str,
        user_model: str,
        assistant_model: str,
        relationship: str,
        desired_behaviors: list[str] | None = None,
        version: str = "1.0.0",
    ) -> dict[str, Any]:
        reg = self.load_registry()
        if presentation not in reg["affects"]:
            raise ValueError(f"Unknown presentation affect '{presentation}'")
        if user_model not in reg["user_models"]:
            raise ValueError(f"Unknown user_model '{user_model}'")
        if assistant_model not in reg["assistant_models"]:
            raise ValueError(f"Unknown assistant_model '{assistant_model}'")
        if relationship not in reg["relationships"]:
            raise ValueError(f"Unknown relationship '{relationship}'")

        clean_id = frame_id.strip().lower().replace(" ", "_")
        payload = {
            "id": clean_id,
            "version": version,
            "title": title.strip(),
            "description": description.strip(),
            "presentation": presentation,
            "user_model": user_model,
            "assistant_model": assistant_model,
            "relationship": relationship,
            "desired_behaviors": desired_behaviors or [],
        }
        digest = _canonical_digest(payload)
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO custom_frames
                (id, version, title, description, presentation, user_model, assistant_model,
                 relationship, desired_behaviors_json, content_digest, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_id,
                    version,
                    payload["title"],
                    payload["description"],
                    presentation,
                    user_model,
                    assistant_model,
                    relationship,
                    json.dumps(payload["desired_behaviors"]),
                    digest,
                    now_iso,
                ),
            )
            conn.commit()
        return {**payload, "digest": digest, "created_at": now_iso}

    def compile_frame(self, task_prompt: str, frame_id: str) -> dict[str, Any]:
        """Compile a raw task prompt and an InteractionFrame ID into a structured prompt envelope."""
        reg = self.load_registry()
        frame = reg["frames_by_id"].get(frame_id)
        if not frame:
            raise ValueError(f"Unknown InteractionFrame '{frame_id}'")

        affect = reg["affects"][frame["presentation"]]
        user_mod = reg["user_models"][frame["user_model"]]
        asst_mod = reg["assistant_models"][frame["assistant_model"]]
        rel_mod = reg["relationships"][frame["relationship"]]

        manifest_digest = _canonical_digest(
            {
                "frame_digest": frame["digest"],
                "affect_digest": affect["digest"],
                "user_digest": user_mod["digest"],
                "assistant_digest": asst_mod["digest"],
                "relationship_digest": rel_mod["digest"],
            }
        )

        system_lines = [
            f"# Interaction Frame: {frame['title']} (id={frame['id']}@{frame['version']}, digest={manifest_digest})",
            "",
            f"## 1. Assistant Identity: {asst_mod['title']} ({asst_mod['id']})",
            f"- Role: {asst_mod['role_definition']}",
            *[f"- Directive: {d}" for d in asst_mod.get("behavioral_directives", [])],
            "",
            f"## 2. User Model: {user_mod['title']} ({user_mod['id']})",
            f"- Context: {user_mod['context_assumptions']}",
            *[f"- Adaptation: {r}" for r in user_mod.get("adaptation_rules", [])],
            "",
            f"## 3. Relationship Contract: {rel_mod['title']} ({rel_mod['id']})",
            f"- Dynamics: {rel_mod['dynamics']}",
            *[f"- Contract: {c}" for c in rel_mod.get("interaction_contract", [])],
            "",
            f"## 4. Presentation / Affect: {affect['title']} ({affect['id']})",
            f"- Tone: {affect['tone']}",
            *[f"- Style Marker: {m}" for m in affect.get("linguistic_markers", [])],
            *[f"- Constraint: {c}" for c in affect.get("constraints", [])],
        ]
        system_prompt = "\n".join(system_lines)
        full_prompt = f"{system_prompt}\n\n---\n\n## Task\n{task_prompt.strip()}"

        return {
            "frame_id": frame["id"],
            "frame_title": frame["title"],
            "frame_version": frame["version"],
            "manifest_digest": manifest_digest,
            "components": {
                "presentation": affect,
                "user_model": user_mod,
                "assistant_model": asst_mod,
                "relationship": rel_mod,
            },
            "system_prompt": system_prompt,
            "user_prompt": task_prompt.strip(),
            "compiled_prompt": full_prompt,
            "compiled_char_length": len(full_prompt),
            "estimated_prompt_tokens": max(1, len(full_prompt) // 4),
        }

    @staticmethod
    def _synthesize_framed_preview(task_prompt: str, compiled: dict[str, Any]) -> str:
        """Produce a deterministic, frame-authentic baseline/variant structural preview when no live LLM API key is configured, clearly labeled as a deterministic frame simulation (FND-0013 / DEC-0010)."""
        comp = compiled["components"]
        affect_id = comp["presentation"]["id"]
        asst_id = comp["assistant_model"]["id"]
        user_id = comp["user_model"]["id"]
        rel_id = comp["relationship"]["id"]

        if affect_id == "cute" and asst_id == "mentor":
            return (
                "[Deterministic Frame Preview — Cute + Overwhelmed Builder + Mentor]\n"
                "Take a breath—you don't have to hold all these pieces in your head at once! 🌱 "
                "Let's untangle this together so the system carries the load instead of you:\n\n"
                "1. **What we already have (Exploit first!):** You've already built the hardest building blocks "
                "(SQLite FTS5 indexing, SHA-256 manifests, and local loopback UIs). We can snap those together right now.\n"
                "2. **Smallest high-leverage step:** Let's wire a single read-only index over your repos, queues, and chats first, "
                "so you have one search box and one status view today.\n"
                "3. **What we can safely defer:** Don't worry about multi-repo splits or automated routing until we run 3 real tasks through the labbench.\n\n"
                f"-> *Applied Frame:* `{compiled['frame_id']}` (`{affect_id}` / `{user_id}` / `{asst_id}` / `{rel_id}`)"
            )
        if affect_id == "caveman":
            return (
                "[Deterministic Frame Preview — Caveman + Principal Engineer + Peer]\n"
                "STOP REBUILDING WHEELS. DO THIS:\n\n"
                "- **PROBLEM:** Human act like message bus across 13 repos + chats + backlogs.\n"
                "- **EXPLOIT NOW:**\n"
                "  1. `git status --porcelain` -> portfolio view.\n"
                "  2. `sqlite3 FTS5` -> index markdown + `.jsonl` chats in place.\n"
                "  3. Parse `BACKLOG.md` tables -> surface `Awaiting acceptance` + `Blocked`.\n"
                "- **EXPLORE ONLY:** `InteractionFrame` 4-tuple eval bench (`Presentation`, `User`, `Assistant`, `Relationship`).\n"
                "- **SKIP:** New microservices, custom vector DB, speculative router before benchmark data.\n\n"
                f"-> *Frame Digest:* `{compiled['manifest_digest']}`"
            )
        if affect_id == "executive" or asst_id == "critic":
            return (
                "[Deterministic Frame Preview — Executive + Systems Owner + Critic / Reviewer]\n"
                "**BLUF / Architectural Assessment:**\n"
                "- **Primary Risk:** Creating parallel authoritative queues or mutating sibling repositories without explicit human cutover violates `DEC-0008` and `DEC-0011`.\n"
                "- **Recommendation:** Deploy a read-only local Control Plane backed by disposable derived SQLite views (`PAT-0003`).\n"
                "- **Blocking Gates to Verify:**\n"
                "  1. Raw chat transcripts must stay outside Git with secret redaction (`DEC-0004`).\n"
                "  2. Frame evaluation results must distinguish deterministic simulations from live model trials (`FND-0013`).\n"
                "  3. `verify-ontology` (`SKL-0007`) must pass with 0 errors across all upstream/downstream links.\n\n"
                f"-> *Frame Digest:* `{compiled['manifest_digest']}`"
            )
        if affect_id == "academic" or asst_id == "professor":
            return (
                "[Deterministic Frame Preview — Academic + Researcher + Professor]\n"
                "**Formal Problem Decomposition & Experimental Protocol:**\n"
                "1. **Hypothesis ($H_1$):** Holding task $T$ and model $M$ constant, varying the structured interaction frame "
                "$F = (P, U, A, R)$ yields statistically distinguishable differences in token efficiency, initiative, and human-rated actionability.\n"
                "2. **Control Baseline ($F_0$):** `baseline_direct` (neutral presentation, standard developer, transactional contract).\n"
                "3. **Confound Control:** Pin prompt digests (`SHA-256`), record exact model snapshot or simulation mode, and blind-score outputs across objective (tokens, latency) and human (usefulness, initiative, specificity) rubrics.\n\n"
                f"-> *Frame Digest:* `{compiled['manifest_digest']}`"
            )
        return (
            "[Deterministic Frame Preview — Baseline Direct]\n"
            "To address this task:\n"
            "1. Consolidate repository status, backlog queues, and documentation search into a local Python service.\n"
            "2. Use SQLite FTS5 for full-text search across markdown files and JSONL session transcripts.\n"
            "3. Define interaction frames in JSON/YAML and compare their compiled prompts and outputs on representative tasks.\n\n"
            f"-> *Frame Digest:* `{compiled['manifest_digest']}`"
        )

    def _try_live_llm(self, system_prompt: str, user_prompt: str) -> tuple[str | None, str]:
        """Attempt live OpenAI-compatible completion if OPENAI_API_KEY is set in environment; otherwise return None."""
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            return None, "deterministic-preview (set OPENAI_API_KEY for live model calls)"
        model = os.environ.get("INTERACTION_LAB_MODEL", "gpt-4o-mini")
        url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        payload = json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.3,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                return content, f"live-llm:{model}"
        except Exception as exc:
            return None, f"deterministic-preview (live call failed: {exc})"

    def run_side_by_side_evaluation(
        self,
        task_prompt: str,
        frame_ids: list[str],
        desired_behavior: str = "general",
        notes: str = "",
    ) -> dict[str, Any]:
        """Execute a side-by-side comparison of multiple InteractionFrames on the same task and persist the run."""
        if not task_prompt.strip():
            raise ValueError("Task prompt cannot be empty.")
        if not frame_ids:
            raise ValueError("Select at least one InteractionFrame to evaluate.")

        variants: list[dict[str, Any]] = []
        execution_mode = "deterministic-preview"
        for fid in frame_ids:
            t0 = time.perf_counter()
            compiled = self.compile_frame(task_prompt, fid)
            live_out, mode_label = self._try_live_llm(
                compiled["system_prompt"], compiled["user_prompt"]
            )
            execution_mode = mode_label
            output_text = (
                live_out if live_out is not None else self._synthesize_framed_preview(task_prompt, compiled)
            )
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            out_tokens = max(1, len(output_text) // 4)
            variants.append(
                {
                    "frame_id": compiled["frame_id"],
                    "frame_title": compiled["frame_title"],
                    "manifest_digest": compiled["manifest_digest"],
                    "components": {
                        "presentation": compiled["components"]["presentation"]["id"],
                        "user_model": compiled["components"]["user_model"]["id"],
                        "assistant_model": compiled["components"]["assistant_model"]["id"],
                        "relationship": compiled["components"]["relationship"]["id"],
                    },
                    "compiled_prompt": compiled["compiled_prompt"],
                    "output_text": output_text,
                    "metrics": {
                        "prompt_tokens_est": compiled["estimated_prompt_tokens"],
                        "output_tokens_est": out_tokens,
                        "total_tokens_est": compiled["estimated_prompt_tokens"] + out_tokens,
                        "latency_ms": elapsed_ms,
                    },
                    "ratings": {
                        "usefulness": None,
                        "actionability": None,
                        "initiative": None,
                        "specificity": None,
                        "winner": False,
                    },
                }
            )

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        run_id = "EVAL-" + _canonical_digest({"ts": now_iso, "task": task_prompt, "frames": frame_ids})[:10].upper()

        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO evaluation_runs
                (run_id, created_at, task_prompt, desired_behavior, execution_mode,
                 baseline_frame_id, variants_json, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    now_iso,
                    task_prompt.strip(),
                    desired_behavior,
                    execution_mode,
                    frame_ids[0],
                    json.dumps(variants),
                    notes,
                ),
            )
            conn.commit()

        return {
            "run_id": run_id,
            "created_at": now_iso,
            "task_prompt": task_prompt.strip(),
            "desired_behavior": desired_behavior,
            "execution_mode": execution_mode,
            "baseline_frame_id": frame_ids[0],
            "variants": variants,
            "notes": notes,
        }

    def record_human_rating(
        self,
        run_id: str,
        frame_id: str,
        usefulness: int,
        actionability: int,
        initiative: int,
        specificity: int,
        winner: bool = False,
        notes: str = "",
    ) -> dict[str, Any]:
        """Persist human judgment scores (1-5) and winner selection for an evaluated frame variant."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM evaluation_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Evaluation run '{run_id}' not found")
            variants = json.loads(row["variants_json"])
            updated = False
            for v in variants:
                if winner:
                    v["ratings"]["winner"] = v["frame_id"] == frame_id
                if v["frame_id"] == frame_id:
                    v["ratings"] = {
                        "usefulness": int(usefulness),
                        "actionability": int(actionability),
                        "initiative": int(initiative),
                        "specificity": int(specificity),
                        "winner": bool(winner),
                    }
                    updated = True
            if not updated:
                raise ValueError(f"Frame '{frame_id}' not in run '{run_id}'")
            new_notes = notes.strip() if notes.strip() else row["notes"]
            conn.execute(
                "UPDATE evaluation_runs SET variants_json = ?, notes = ? WHERE run_id = ?",
                (json.dumps(variants), new_notes, run_id),
            )
            conn.commit()
        return self.get_run(run_id)  # type: ignore[return-value]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM evaluation_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            return {
                "run_id": row["run_id"],
                "created_at": row["created_at"],
                "task_prompt": row["task_prompt"],
                "desired_behavior": row["desired_behavior"],
                "execution_mode": row["execution_mode"],
                "baseline_frame_id": row["baseline_frame_id"],
                "variants": json.loads(row["variants_json"]),
                "notes": row["notes"],
            }

    def list_runs(self, limit: int = 25) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM evaluation_runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [
                {
                    "run_id": r["run_id"],
                    "created_at": r["created_at"],
                    "task_prompt": r["task_prompt"],
                    "desired_behavior": r["desired_behavior"],
                    "execution_mode": r["execution_mode"],
                    "baseline_frame_id": r["baseline_frame_id"],
                    "variants": json.loads(r["variants_json"]),
                    "notes": r["notes"],
                }
                for r in rows
            ]
