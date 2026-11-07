"""Bounded lexical lookup over caller-supplied, owner-owned precedent records."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .safety import SECRET_RE

MAX_RECORDS = 50
MAX_EVENTS = 200
MAX_INPUT_BYTES = 64 * 1024
MAX_RESULTS = 20
OUTCOMES = {"success", "failure", "mixed", "inconclusive", "unknown"}
EVENT_TYPES = {"observation", "correction", "dispute"}
SCOPE_FIELDS = ("runtime", "input", "constraints")
TOKEN_RE = re.compile(r"[a-z0-9_]+")
STOP_WORDS = {"a", "an", "and", "are", "as", "at", "be", "by", "do", "for", "from",
              "in", "is", "it", "of", "on", "or", "that", "the", "this", "to", "with"}
AVOIDANCE_TERMS = {"avoid", "avoidance", "failure", "failed", "prevent", "risk", "hazard",
                   "regression", "unsafe", "without"}
NOTICE = (
    "Caller-supplied records are not independently verified. Retrieval relevance is not "
    "applicability, evidence quality, trust, or endorsement. No source is opened or fetched; "
    "no code is executed, feedback is stored, or canonical record is changed."
)


class PrecedentError(ValueError):
    """Invalid caller-supplied precedent request."""


def _text(value: Any, name: str, maximum: int, *, empty: bool = False) -> str:
    if (not isinstance(value, str) or len(value) > maximum or "\0" in value
            or (not empty and not value.strip()) or SECRET_RE.search(value)):
        raise PrecedentError(f"{name} must be a non-sensitive string of at most {maximum} characters")
    return value


def _revision(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name, 200)


def _tokens(value: str) -> set[str]:
    return {token for token in TOKEN_RE.findall(value.casefold()) if len(token) > 1 and token not in STOP_WORDS}


def _normalize_scope(value: str) -> str:
    return " ".join(value.casefold().split())


def _validate_records(records: Any) -> list[dict[str, Any]]:
    try:
        encoded = json.dumps(records, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise PrecedentError("records must be valid JSON data") from None
    if len(encoded) > MAX_INPUT_BYTES:
        raise PrecedentError("records exceed the 64 KiB input limit")
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise PrecedentError(f"records must be an array of at most {MAX_RECORDS} entries")

    clean: list[dict[str, Any]] = []
    seen_records: set[str] = set()
    total_events = 0
    for raw in records:
        if not isinstance(raw, dict) or set(raw) != {
            "record_id", "record_revision", "record_ref", "technique", "implementation", "observations",
        }:
            raise PrecedentError("each record requires exactly the documented precedent fields")
        record_id = _text(raw["record_id"], "record_id", 200)
        if record_id in seen_records:
            raise PrecedentError("record_id values must be unique in one request")
        seen_records.add(record_id)
        record_ref = _text(raw["record_ref"], "record_ref", 2000)
        technique = raw["technique"]
        if not isinstance(technique, dict) or set(technique) != {"id", "title", "summary"}:
            raise PrecedentError("technique requires exactly id, title, and summary")
        technique_clean = {
            "id": _text(technique["id"], "technique.id", 200),
            "title": _text(technique["title"], "technique.title", 200),
            "summary": _text(technique["summary"], "technique.summary", 4000, empty=True),
        }
        implementation = raw["implementation"]
        if not isinstance(implementation, dict) or set(implementation) != {"id", "source_ref", "revision"}:
            raise PrecedentError("implementation requires exactly id, source_ref, and revision")
        implementation_clean = {
            "id": _text(implementation["id"], "implementation.id", 200),
            "source_ref": _text(implementation["source_ref"], "implementation.source_ref", 2000),
            "revision": _revision(implementation["revision"], "implementation.revision"),
        }
        observations = raw["observations"]
        if not isinstance(observations, list):
            raise PrecedentError("observations must be an array")
        total_events += len(observations)
        if total_events > MAX_EVENTS:
            raise PrecedentError(f"records may contain at most {MAX_EVENTS} observations")
        event_ids: set[str] = set()
        event_types: dict[str, str] = {}
        clean_events: list[dict[str, Any]] = []
        for event in observations:
            required = {"event_id", "event_type", "target_id", "need", "outcome", "scope",
                        "summary", "source_ref", "revision"}
            if not isinstance(event, dict) or set(event) != required:
                raise PrecedentError("observations require exactly the documented event fields")
            event_id = _text(event["event_id"], "event_id", 200)
            if event_id in event_ids:
                raise PrecedentError("event_id values must be unique within a record")
            event_ids.add(event_id)
            event_type = _text(event["event_type"], "event_type", 20)
            if event_type not in EVENT_TYPES:
                raise PrecedentError("event_type must be observation, correction, or dispute")
            target_id = _text(event["target_id"], "target_id", 200, empty=True)
            if event_type == "observation" and target_id:
                raise PrecedentError("observation target_id must be empty")
            if event_type != "observation" and event_types.get(target_id) != "observation":
                raise PrecedentError("corrections and disputes must target an earlier observation")
            outcome = _text(event["outcome"], "outcome", 20)
            if outcome not in OUTCOMES:
                raise PrecedentError("unsupported observation outcome")
            if event_type == "dispute" and outcome != "unknown":
                raise PrecedentError("dispute events must use unknown outcome")
            scope = event["scope"]
            if not isinstance(scope, dict) or set(scope) != set(SCOPE_FIELDS):
                raise PrecedentError("scope requires runtime, input, and constraints")
            scope_clean = {
                field: _text(scope[field], f"scope.{field}", 500, empty=True)
                for field in SCOPE_FIELDS
            }
            clean_events.append({
                "event_id": event_id,
                "event_type": event_type,
                "target_id": target_id,
                "need": _text(event["need"], "need", 2000, empty=True),
                "outcome": outcome,
                "scope": scope_clean,
                "summary": _text(event["summary"], "summary", 4000),
                "source_ref": _text(event["source_ref"], "observation.source_ref", 2000),
                "revision": _revision(event["revision"], "observation.revision"),
            })
            event_types[event_id] = event_type
        clean.append({
            "record_id": record_id,
            "record_revision": _revision(raw["record_revision"], "record_revision"),
            "record_ref": record_ref,
            "technique": technique_clean,
            "implementation": implementation_clean,
            "observations": clean_events,
        })
    return clean


def _context(value: Any) -> dict[str, str]:
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - set(SCOPE_FIELDS):
        raise PrecedentError("context may contain only runtime, input, and constraints")
    return {
        field: _text(value.get(field, ""), f"context.{field}", 500, empty=True)
        for field in SCOPE_FIELDS
    }


def _event_fingerprint(event: dict[str, Any]) -> str:
    source = event.get("effective", event)
    content = {key: source[key] for key in ("need", "outcome", "scope", "summary", "source_ref", "revision")}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _scope_comparison(scope: dict[str, str], context: dict[str, str]) -> dict[str, str]:
    result = {}
    for field in SCOPE_FIELDS:
        requested = context[field]
        observed = scope[field]
        result[field] = (
            "unknown" if not requested or not observed else
            "match" if _normalize_scope(requested) == _normalize_scope(observed) else "different"
        )
    return result


def _effective_events(record: dict[str, Any]) -> list[dict[str, Any]]:
    events = record["observations"]
    corrections: dict[str, list[dict[str, Any]]] = {}
    disputes: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if event["event_type"] == "correction":
            corrections.setdefault(event["target_id"], []).append(event)
        elif event["event_type"] == "dispute":
            disputes.setdefault(event["target_id"], []).append(event)
    for event in events:
        if event["event_type"] != "observation":
            continue
        event["duplicate_of"] = None
        correction_history = corrections.get(event["event_id"], [])
        correction = correction_history[-1] if correction_history else None
        event["effective"] = {
            "outcome": correction["outcome"] if correction else event["outcome"],
            "need": correction["need"] if correction else event["need"],
            "scope": correction["scope"] if correction else event["scope"],
            "summary": correction["summary"] if correction else event["summary"],
            "source_ref": correction["source_ref"] if correction else event["source_ref"],
            "revision": correction["revision"] if correction else event["revision"],
        }
        event["corrections"] = correction_history
        event["disputes"] = disputes.get(event["event_id"], [])
    return events


def _variants(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str | None], dict[str, Any]] = {}
    for record in records:
        technique = record["technique"]
        implementation = record["implementation"]
        key = (technique["id"], implementation["id"], implementation["source_ref"], implementation["revision"])
        variant = grouped.get(key)
        if variant is None:
            variant = {
                "technique": technique,
                "implementation": implementation,
                "records": [],
                "events": [],
            }
            grouped[key] = variant
        elif variant["technique"] != technique:
            raise PrecedentError("one technique id cannot have conflicting descriptions in a request")
        variant["records"].append(record)
        events = _effective_events(record)
        for event in events:
            event["record_id"] = record["record_id"]
            event["event_key"] = f"{record['record_id']}:{event['event_id']}"
        variant["events"].extend(events)
    for variant in grouped.values():
        seen_evidence: dict[str, str] = {}
        for event in variant["events"]:
            if event["event_type"] != "observation":
                continue
            fingerprint = _event_fingerprint(event)
            event["duplicate_of"] = seen_evidence.get(fingerprint)
            if fingerprint not in seen_evidence:
                seen_evidence[fingerprint] = event["event_key"]
    return list(grouped.values())


def _relevant_events(variant: dict[str, Any], query_tokens: set[str], context: dict[str, str]) -> list[dict[str, Any]]:
    relevant = []
    for event in variant["events"]:
        if event["event_type"] != "observation":
            continue
        effective = event["effective"]
        haystack = " ".join([effective["need"], effective["summary"], effective["outcome"],
                             *(effective["scope"][field] for field in SCOPE_FIELDS)])
        matched = bool(query_tokens & _tokens(haystack))
        scoped = any(_scope_comparison(effective["scope"], context)[field] == "match" for field in SCOPE_FIELDS)
        if matched or scoped:
            relevant.append(event)
    return relevant


def _event_view(event: dict[str, Any]) -> dict[str, Any]:
    effective = event["effective"]
    return {
        "record_id": event["record_id"],
        "event_id": event["event_id"],
        "outcome": event["outcome"],
        "need": event["need"],
        "scope": event["scope"],
        "summary": event["summary"],
        "source_ref": event["source_ref"],
        "revision": event["revision"],
        "corrections": [{
            "record_id": event["record_id"],
            "event_id": correction["event_id"],
            "outcome": correction["outcome"],
            "summary": correction["summary"],
            "scope": correction["scope"],
            "source_ref": correction["source_ref"],
            "revision": correction["revision"],
        } for correction in event["corrections"]],
        "disputes": [{
            "record_id": event["record_id"], "event_id": dispute["event_id"], "summary": dispute["summary"],
            "source_ref": dispute["source_ref"], "revision": dispute["revision"],
        } for dispute in event["disputes"]],
        "duplicate_of": event["duplicate_of"],
        "effective_outcome": effective["outcome"],
    }


def _warnings(events: list[dict[str, Any]]) -> list[str]:
    warnings = []
    for event in events:
        effective = event["effective"]
        scope = ", ".join(f"{key}={value}" for key, value in effective["scope"].items() if value) or "scope unknown"
        if effective["outcome"] in {"failure", "mixed", "inconclusive"}:
            warnings.append(
                f"{effective['outcome'].capitalize()} evidence under {scope}; it does not establish outcomes "
                f"for other revisions or conditions. Evidence: {effective['summary']}"
            )
        if effective["outcome"] == "unknown":
            warnings.append(
                f"Outcome is unknown under {scope}; absence of a reported failure is not success. "
                f"Evidence: {effective['summary']}"
            )
        if event["disputes"]:
            warnings.append(f"Evidence {event['event_key']} is disputed; inspect its full history.")
        if event["duplicate_of"]:
            warnings.append(f"Evidence {event['event_key']} duplicates {event['duplicate_of']}; it is not independent support.")
    return list(dict.fromkeys(warnings))


def find_precedents(
    query: str,
    records: Any,
    context: Any = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Find relevant technique/implementation revisions without claiming applicability."""
    query = _text(query, "query", 2000)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RESULTS:
        raise PrecedentError(f"limit must be an integer from 1 to {MAX_RESULTS}")
    query_tokens = _tokens(query)
    if not query_tokens:
        raise PrecedentError("query must contain at least one searchable term")
    requested_context = _context(context)
    validated = _validate_records(records)
    avoidance = bool(query_tokens & AVOIDANCE_TERMS)
    results = []
    for variant in _variants(validated):
        technique = variant["technique"]
        implementation = variant["implementation"]
        events = _relevant_events(variant, query_tokens, requested_context)
        fields = {
            "technique.title": technique["title"],
            "technique.summary": technique["summary"],
            "need": " ".join(event["effective"]["need"] for event in events),
            "evidence": " ".join(event["effective"]["summary"] for event in events),
            "scope": " ".join(event["effective"]["scope"][name] for event in events for name in SCOPE_FIELDS),
            "implementation": " ".join((implementation["id"], implementation["source_ref"])),
        }
        matched_terms = sorted(token for token in query_tokens if any(token in _tokens(value) for value in fields.values()))
        if not matched_terms:
            continue
        matched_fields = [name for name, value in fields.items() if query_tokens & _tokens(value)]
        score = sum(3 if name in {"technique.title", "need"} else 2 if name in {"evidence", "scope"} else 1
                    for name in matched_fields)
        relevant = [event for event in events if not event["duplicate_of"]]
        outcome_summary = {
            "observed_outcomes": sorted({event["effective"]["outcome"] for event in relevant}),
            "evidence_entries": len(relevant),
            "independent_support": "not assessed; source correlation is unverified",
        } if relevant else None
        negative = any(event["effective"]["outcome"] in {"failure", "mixed", "inconclusive"}
                       or event["disputes"] for event in events)
        scope_comparisons = {
            event["event_key"]: _scope_comparison(event["effective"]["scope"], requested_context)
            for event in events
        }
        record_sources = [{
            "record_id": record["record_id"], "record_ref": record["record_ref"],
            "record_revision": record["record_revision"],
        } for record in variant["records"]]
        results.append({
            "technique": technique,
            "implementation": implementation,
            "source_records": record_sources,
            "relevant_evidence": [_event_view(event) for event in events],
            "outcome_summary": outcome_summary,
            "outcome_provenance": "caller-supplied; not independently verified",
            "applicability": "not assessed; context comparisons are exact label matches only",
            "scope_comparison": scope_comparisons,
            "evidence_quality": {
                "scope_fields_present": sorted({
                    field for event in relevant for field, value in event["effective"]["scope"].items() if value
                }),
                "scope_fields_missing": sorted({
                    field for event in relevant for field, value in event["effective"]["scope"].items() if not value
                }),
                "independence_verified": False,
                "duplicate_observations": sum(1 for event in events if event["duplicate_of"]),
                "source_integrity": "not verified",
            },
            "ranking": {
                "method": "deterministic lexical term overlap",
                "relevance_score": score,
                "matched_terms": matched_terms,
                "matched_fields": matched_fields,
                "intent": "avoidance" if avoidance else "general",
                "avoidance_priority": avoidance and negative,
            },
            "warnings": _warnings(events) + ([] if events else [
                "No outcome observation matched this need/context; applicability and outcome remain unknown.",
            ]),
        })
    results.sort(key=lambda result: (
        not result["ranking"]["avoidance_priority"] if avoidance else False,
        -result["ranking"]["relevance_score"],
        result["technique"]["id"],
        result["implementation"]["id"],
        result["implementation"]["revision"] or "",
    ))
    return {
        "schema_version": 1,
        "query": query,
        "context": requested_context,
        "results": results[:limit],
        "coverage": {"records_supplied": len(validated), "variants_matched": len(results),
                     "records_fetched": False, "local_index_used": False},
        "notice": NOTICE,
    }


def inspect_precedent(implementation_id: str, records: Any) -> dict[str, Any]:
    """Inspect all supplied revision-scoped evidence history for an implementation."""
    implementation_id = _text(implementation_id, "implementation_id", 200)
    validated = _validate_records(records)
    matches = [
        variant for variant in _variants(validated)
        if variant["implementation"]["id"] == implementation_id
    ]
    variants = []
    for variant in matches:
        events = [event for event in variant["events"] if event["event_type"] == "observation"]
        variants.append({
            "technique": variant["technique"],
            "implementation": variant["implementation"],
            "source_records": [{
                "record_id": record["record_id"], "record_ref": record["record_ref"],
                "record_revision": record["record_revision"],
            } for record in variant["records"]],
            "evidence_history": [_event_view(event) for event in events],
            "event_history": [{
                "record_id": event["record_id"],
                "event_id": event["event_id"],
                "event_type": event["event_type"],
                "target_id": event["target_id"],
                "need": event["need"],
                "outcome": event["outcome"],
                "scope": event["scope"],
                "summary": event["summary"],
                "source_ref": event["source_ref"],
                "revision": event["revision"],
            } for event in variant["events"]],
            "warnings": _warnings(events),
        })
    return {
        "schema_version": 1,
        "implementation_id": implementation_id,
        "variants": variants,
        "notice": NOTICE,
    }
