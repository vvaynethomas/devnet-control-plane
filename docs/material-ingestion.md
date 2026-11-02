# Explicit material ingestion: bounded first slice

Explicitly supplied material goes through one local phone-home submission. A repo
is one possible source, not a required membership or ownership boundary. Material
format selects a suitable static adapter, not eligibility. No repo registration,
product membership, inventory match, agent report, destination acceptance or
second approval is required. Repository opt-in applies only to the separate
whole-repository `digest scan` operation.

The existing `PhoneHome.submit` service, CLI JSON submit, loopback
`POST /api/phone-home/submissions` and optional local MCP `phone_home_submit`
accept the same material variant:

```json
{
  "schema_version": 1,
  "kind": "material",
  "material": {
    "name": "notes.md",
    "format": "markdown",
    "identity": "original-source:notes-7",
    "text": "# Import notes\nGoal: reuse the existing adapter\nOther observations"
  },
  "target": "reuse",
  "source_ref": "original local reference or URL, never fetched",
  "source_session": "optional session reference",
  "idempotency_key": "optional caller key"
}
```

Only `kind` and `material` are required; material requires `name`, `format` and
exactly one of `text` or strictly validated `base64`. ZIP requires base64.
`identity` defaults to the supplied name. No server API accepts filesystem paths
to read: `name`, identity and source references are metadata, not read/fetch
instructions. Existing discovery/tool/etc. report submissions keep their current
validation contract.

For explicitly selected local files:

```powershell
devnet phone-home ingest 'C:\inputs\notes.md' --target reuse
devnet phone-home ingest 'C:\inputs\bundle.zip'
devnet phone-home ingest 'C:\inputs\unusual-extension' --format text --identity 'original:7'
devnet phone-home intake export INTAKE-returned-uuid
```

The CLI infers `.txt`, `.md`, `.csv`, `.html`, `.htm`, `.json`, `.py`, and `.zip`;
otherwise the caller must specify a format. It reads only the named file, not
its parent, repo or neighboring files. CLI identity defaults to the explicit
absolute path. `--source-ref`, `--source-session` and `--idempotency-key`
preserve caller context. Global root/data options still go before `phone-home`.

## Reuse and local processing

Priority 1's existing phone-home check identified the existing intake as a reuse
candidate. This implementation extends that intake and the existing
`Digester.digest(MaterialReference, target) -> Digestion` contract, not a new
product/store. `SuppliedMaterialDigester` is pure extraction with byte-hash
revision verification; persistence remains in `phone_home.sqlite`. Repository
Git/manifest extractors remain unchanged because explicitly supplied streams
need neither repository enumeration nor registration. Python AST, CSV, HTML,
JSON and ZIP use Python's existing standard library (`ast`, `csv`,
`html.parser`, `json`, `zipfile`); no third-party parser, downloaded extractor
or LLM is required. No live external component search was performed or is
required at ingestion.

## Exact coverage

| Adapter | Extracted evidence | Coverage gaps / residue |
|---|---|---|
| `text` | Nonempty UTF-8 lines and explicit labeled directions. | No semantic classification or inferred purpose; display truncations and output caps are visible. |
| `markdown` | ATX headings and labeled directions outside backtick/tilde fences. | Ordinary body, frontmatter, setext headings and fenced lines remain observations/residue; links and embedded formats are not interpreted. |
| `csv` | Comma-separated rows with the standard Excel CSV dialect; header and row items, including quoted multiline fields. Direction columns are `goal`, `intent`, `direction`, `purpose`, `decision` (case-insensitive). | No delimiter/type/schema inference or formula evaluation. Ragged rows remain observations with counted gaps; malformed quoting reports a parse gap, possibly after valid prefix rows. |
| `html` | `HTMLParser` text data, entities decoded, with explicit labeled directions. | Scripts/styles/templates are not interpreted or returned as text. Markup, attributes, comments and hidden regions are coverage gaps; no DOM/rendering/accessibility fidelity. Malformed markup uses the standard parser's permissive recovery. No links, images or resources are fetched. |
| `json` | JSON objects, arrays and primitive values as provisional structure/value observations. Object members are traversed in sorted-key order; arrays retain index order. Each observation carries a bounded JSON Pointer (RFC 6901 escaping), SHA-256/revision provenance and a document-level location marker. | No schema, domain meaning, trust, canonical status, or intent is inferred. Duplicate keys, non-standard constants and malformed JSON produce `json_parse_failed`; out-of-range numbers, sensitive-named fields and recognized secret values are omitted with gaps. |
| `python` | Top-level function/async function/class declaration lines after `ast.parse`. | Imports, comments, docstrings, bodies, private and nested source remain bounded line observations, not runtime analysis. No imports, evaluation or execution; malformed syntax reports a parse gap. No direction inferred from Python strings/comments. |
| `zip` | Supported members processed in archive order through the above adapters, in memory. | Unsupported suffixes and nested ZIPs remain named gaps with container provenance; no recursion, extraction or execution. |

For text/Markdown/HTML only, direction requires a line/text-node beginning with
`TODO:`, `FIXME:`, `goal:`, `intent:`, `direction:`, `decision:` or `purpose:`
(optional Markdown list marker). These are **declared** observations, not verified
intent, authorization or adopted decisions. CSV direction is a named field, not
inference. Target focus marks evidence but does not discard untargeted content.
No semantic novelty, suitability, trust, waste or ecological stance is inferred.

Original material identity, caller references, SHA-256 revision, extractor
name/version and per-file SHA-256/size/path remain distinct from canonical
knowledge. ZIP members carry the outer container hash and original member path.
Lines are 1-based; CSV row evidence starts at the physical row's first line;
HTML evidence points to the text node's start line. CSV display is a JSON array
with row order preserved, not a typed record. SHA-256 covers original bytes,
including BOM/newlines; UTF-8 BOM is tolerated for parsing.

Items remain provisional with deterministic IDs. Residue groups include all
observed normalized full texts (including extracted/untargeted content), full
normalized hashes, display truncation flags, occurrence counts and up to three
references. Repeated items retain distinct line IDs; frequency is not waste,
independence, corroboration or trust. Distinct long observations are not merged
because truncated display prefixes happen to match. Output truncation and
unparsed/unsupported regions are visible as counts and bounded gap references.
JSON scalar observations use compact JSON value notation and preserve string
whitespace exactly; object/array observations state their type and member/item
count, while each child is independently observed at its JSON Pointer. JSON
evidence does not claim exact source line offsets. Identical encoded scalar
values share residue groups with distinct pointer references; distinct string
values are not merged merely because their words differ only in whitespace.
Untargeted observations remain present.

## Hard limits and refusals

Requests keep phone-home's 64 KiB serialized-JSON limit. Input bytes are capped
at **32 KiB** (including compressed ZIP bytes). ZIPs allow at most **32 entries**
(including directories), **32 KiB per member**, **128 KiB total declared
uncompressed content**, and a maximum **100:1** member compression ratio.
Only stored/deflated ZIPs are supported. All central-directory entries are
preflighted before supported members are read, and reads are bounded independently.
CRC/read errors, encrypted members, links/devices/nonregular types, unsafe paths,
duplicate case-insensitive paths, invalid archives and excess limits refuse the
entire submission: no partial receipt is saved.

Unsafe paths include absolute/traversing/dot/empty components, backslashes,
drive/ADS colons, Windows reserved device names, trailing dot/space components,
control characters, truncated NUL names and names longer than 500 characters.
ZIP processing never calls `extract`, writes files, follows links, or descends
into nested archives. Unsupported member content is not decompressed.

Each digestion returns at most **64 items**, **256 observations**, **30 grouped
observations**, **3 references per group**, **64 gap references**, and **32 member
file-evidence records**. Titles show 200 characters, details/group displays 300;
truncation flags preserve the distinction from full hashes. Overflow is counted,
not silently claimed as complete. Non-UTF-8, NUL/binary content, recognized token
patterns and sensitive filename patterns are omitted with visible gaps; parser
failures never echo source snippets. Detection is incomplete: do not submit
secrets or sensitive data. Filename and source metadata are still local evidence.
An unsupported top-level format fails validation rather than selecting a default.
JSON additionally visits at most **512 records across a submission**, limits
nested values to **16 levels**, and displays at most **300 JSON Pointer
characters** per evidence reference (with a full pointer hash when truncated).
Sensitive field-name handling is a narrow omission guard, not a general secret
scanner; escaped values matching recognized token patterns are omitted too.

The SQLite inbox is local and **unencrypted**. The caller's raw bytes/base64 are
not copied into storage; bounded extracted snippets and hashes **are** stored,
and for small text may represent most/all of its content. Callers must retain
originals if they want to resolve hashes or revisit omitted content. Receipts,
UTC timestamps, idempotency and list/get/export reuse the existing intake.
Provisional status describes evidence/canonical separation, not a second ingest
acceptance stage. Human approval is required only for consequential later
execution, adoption or canonical promotion; none is implemented automatically.

Deferred: arbitrary encodings, PDFs, Office documents, images/OCR, TOML material
adapter, other source languages, delimiter inference, nested/encrypted archives,
larger/streaming uploads and cross-material semantic digestion. TOML remains
deferred because the package supports Python 3.10, before `tomllib` is in the
standard library; no dependency is added for this bounded slice.
No auto-promotion, dispatch, watcher/scheduler, utility chest, external
transmission, new product ownership, or mandatory agent reporting is introduced.
