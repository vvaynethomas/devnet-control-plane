# The network's front door

The owner decided on 2026-11-11 that the control plane is how IDEs and chats reach the
network, and that requests for new work go through it instead of being carried by hand
between the registry, the incubator and each repository. This is the first working version.
The decisions behind it are working defaults; the registry's `PRINCIPLES.md` states them.

## What it adds

| Command | MCP tool | What it does |
| --- | --- | --- |
| `devnet bootstrap` | `network_bootstrap` | Under 5 KB: the principles, how to ask for things, playbook names, what is open |
| `devnet lessons ask "<task>" --repo R --stage S` | `lessons_ask` | Asks the Epistemic Service, which owns lessons and evidence |
| `devnet playbook list`, `get <name>` | `playbook_list`, `playbook_get` | Procedures read from the registry, the incubator and the harvest playbooks |
| `devnet registry list`, `show <id>` | `registry_list`, `registry_show` | The registry, now also over MCP |
| `devnet commission check/open/decide/progress/get/list` | `commission_*` | The commissioning path, below |

Nothing is copied into the control plane. Playbooks and principles are read where they live;
lessons are asked of the Epistemic Service's own command line (`DEVNET_EPISTEMIC_ROOT`, else
`devnet/epistemic-service/main`). If a service is missing, the answer says `unavailable` and
the rest still works.

## Commissioning path

Follows the registry's `TRIAGE.md`.

1. **check** (read-only): registry entries that share words with the request, the existing
   capability check, lessons for `before-building`, and the playbook to follow (`idea-triage`).
2. **open**: records the request under `<data dir>/commissions/COM-<date>-<slug>.json`. If the
   check showed it is already in the registry, pass `existing_entry` and the commission is
   attached to that entry. Otherwise a new `caught` entry is written. An existing name is
   refused, so there is never a second entry for one thing.
3. **recommend** (triage's product): the outcome advised, reasoning, and sources or a stored decision brief,
   plus the one question for the owner. Only then does the commission reach the owner's queue
   (`awaiting-decision`). Remarks said in passing use `commission note` and create no commission.
4. **decide**: records the owner's outcome, with their words, on the entry with who decided and why: `idea`,
   `routed` or `adopted` (need `home`), `parked`, `set-aside`, or `seed`. A seed needs
   `prior_art`, a `name` and a `category`; the incubator's `init-seed --entry` then creates the
   repository and sets the entry's home. The control plane never decides.
5. **progress**: `in-progress` (a seed becomes `growing`), `blocked` or `done` with a note and
   a reference. `done` is the worker's report, not the owner's acceptance.

Each registry change is committed in the registry checkout on its own, on whatever branch is
checked out there, and never pushed.

## Reaching it from anywhere

`python install_front_door.py` writes `~/.devnet/network.json` (where each node's checkout
is) and launchers in `~/.devnet/bin/`. `python ~/.devnet/bin/devnet.py <command>` then works
from any folder, and `devnet.py mcp` is the MCP server command for any client. To repoint a
node (for example after this branch merges), edit `network.json`.

The `devnet` skill in the registry's `playbooks/` is the small bootstrap every agent sees.

## Not done

- Registry matching is by shared words. It lists candidates; an agent or the owner still has
  to read them.
- `decide` cannot verify who is speaking. It now requires the owner's own words as `quote` and stores the
  decision with `verified: false`, so a decision is the caller's record of what the owner said, visible in
  the registry history. Whether creating a repository (`seed`) should need an owner-run confirmation is an
  open question for the owner; see the brief `recording-owner-decisions-over-mcp`.
- No notification when a commission is waiting; `commission list --state awaiting-decision`
  or `bootstrap` shows them.
- The workbench GUI does not show commissions yet.
- The incubator's seed step runs only for `seed`; `routed` work is not opened as an issue in
  the target repository.
- `test_pillar4_capability_discovery` fails on `main` as well; it is not caused by this.
