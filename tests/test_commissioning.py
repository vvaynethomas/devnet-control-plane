"""Commissioning path and front-door helpers: synthetic registry, incubator and playbooks only."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from control_plane import front_door
from control_plane.cli import main
from control_plane.commissioning import CommissionError, Commissioning

# Stands in for the incubator's init-seed: gives an existing entry a home, as --entry does.
STUB_INIT_SEED = '''import argparse, json, pathlib
p = argparse.ArgumentParser()
p.add_argument("name")
for o in ("--title", "--origin", "--category", "--entry", "--network-root", "--registry-root"):
    p.add_argument(o)
a = p.parse_args()
path = pathlib.Path(a.registry_root) / "entries" / (a.entry + ".json")
entry = json.loads(path.read_text(encoding="utf-8"))
entry["home"] = a.category + "/" + a.name
entry["status"] = "seed" if entry["status"] in ("caught", "idea") else entry["status"]
path.write_text(json.dumps(entry), encoding="utf-8")
print(json.dumps({"created": str(pathlib.Path(a.network_root) / a.category / a.name / "main")}))
'''


class CommissioningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.network, self.data = root / "net", root / "data"
        self.registry = self.network / "devnet" / "network-registry" / "main"
        self.factory = self.network / "devnet" / "AIAD-ex12410" / "main"
        (self.registry / "entries").mkdir(parents=True)
        script = self.factory / ".github" / "skills" / "init-seed" / "scripts" / "init_seed.py"
        script.parent.mkdir(parents=True)
        script.write_text(STUB_INIT_SEED, encoding="utf-8")
        (self.factory / ".github" / "skills" / "init-seed" / "SKILL.md").write_text(
            "---\nname: init-seed\ndescription: \"Start a seed.\"\n---\n# Init Seed\n", encoding="utf-8")
        playbook = self.registry / "playbooks" / "idea-triage"
        playbook.mkdir(parents=True)
        (playbook / "SKILL.md").write_text("---\nname: idea-triage\ndescription: Prepare a decision.\n---\nSteps.\n", encoding="utf-8")
        (self.registry / "PRINCIPLES.md").write_text("# Principles\n\nThe owner decides.\n", encoding="utf-8")
        for args in (["init", "--quiet", "--initial-branch", "main"], ["config", "user.email", "t@example.test"],
                     ["config", "user.name", "T"], ["add", "--all"], ["commit", "--quiet", "-m", "start"]):
            subprocess.run(["git", *args], cwd=self.registry, check=True, capture_output=True)
        self.write_entry({"id": "2026-01-01-lesson-service", "kind": "research", "title": "Lesson Service", "status": "growing",
                          "home": "devnet/lesson-service", "initialized_by": "product-incubator",
                          "initialized_on": "2026-01-01", "origin": "Serve lessons with evidence to agents."})
        self.desk = Commissioning(self.registry, self.data, self.factory, self.network,
                                  capability_check=lambda q: {"existing_tools_and_modules": []},
                                  lessons=lambda task, repo, stage: {"lessons": [{"id": "made-up"}], "stage": stage})

    def write_entry(self, entry: dict) -> None:
        (self.registry / "entries" / f"{entry['id']}.json").write_text(json.dumps(entry), encoding="utf-8")

    def entry(self, entry_id: str) -> dict:
        return json.loads((self.registry / "entries" / f"{entry_id}.json").read_text(encoding="utf-8"))

    def log(self) -> list[str]:
        return subprocess.run(["git", "log", "--format=%s"], cwd=self.registry, check=True, capture_output=True, text=True).stdout.splitlines()

    def test_new_request_goes_from_check_to_seeded_home_to_done(self) -> None:
        checked = self.desk.check("Trip planner", "Plan trips around saved places.")
        self.assertEqual(checked["registry"]["candidates"], [])
        self.assertEqual((checked["playbook"]["name"], checked["lessons"]["stage"]), ("idea-triage", "before-building"))
        opened = self.desk.open("Trip planner", "Plan trips around saved places.", "owner", "products/x")
        entry_id = opened["entry_id"]
        self.assertEqual((opened["state"], opened["entry"]["status"], opened["attached_to_existing"]), ("triage", "caught", False))
        self.assertIn(f"commission:{opened['id']}", self.entry(entry_id)["refs"])
        self.assertEqual(self.entry(entry_id)["initialized_by"], "control-plane")
        self.assertEqual(self.desk.list("awaiting-decision")["count"], 0, "nothing is queued for the owner before triage")
        with self.assertRaises(CommissionError):
            self.desk.progress(opened["id"], "in-progress", "started early", "agent")
        with self.assertRaises(CommissionError):
            self.desk.recommend(opened["id"], "seed", "Because.", "Build it?", "agent", sources=[{"ref": "x"}])  # a source says something
        with self.assertRaises(CommissionError) as unsourced:
            self.desk.recommend(opened["id"], "seed", "Because I think so.", "Build it?", "agent")
        self.assertIn("unsourced", str(unsourced.exception))
        with self.assertRaises(CommissionError):
            Commissioning(self.registry, self.data, self.factory, self.network, brief_lookup=lambda b: {"unavailable": "none"}
                          ).recommend(opened["id"], "seed", "Because.", "Build it?", "agent", brief="no-such-brief")
        advised = self.desk.recommend(opened["id"], "seed", "Nothing like it exists here.", "Start it as a product?", "agent",
                                      sources=[{"ref": "registry:search", "says": "No candidates."}])
        self.assertEqual((advised["state"], advised["recommendation"]["sources"][0]["checked"] != ""), ("awaiting-decision", True))
        self.assertEqual(self.desk.list("awaiting-decision")["count"], 1)
        with self.assertRaises(CommissionError):
            self.desk.decide(opened["id"], "seed", "Worth doing.", "owner")  # a seed needs prior art, a name and a category
        decided = self.desk.decide(opened["id"], "seed", "Worth doing now.", "owner", prior_art="Searched registry; nothing.",
                                   name="trip-planner", category="products")
        self.assertEqual((decided["state"], decided["entry"]["status"], decided["entry"]["home"]), ("decided", "seed", "products/trip-planner"))
        self.assertEqual(self.entry(entry_id)["decision"]["decided_by"], "owner")
        going = self.desk.progress(opened["id"], "in-progress", "First version under way.", "agent")
        self.assertEqual(going["entry"]["status"], "growing")
        done = self.desk.progress(opened["id"], "done", "First version works.", "agent", ref="https://example.test/pr/1")
        self.assertEqual(done["state"], "done")
        self.assertIn("not acceptance", done["next"])
        self.assertIn("https://example.test/pr/1", self.entry(entry_id)["refs"])
        self.assertEqual([h["event"] for h in done["history"]], ["opened", "recommended", "decided", "in-progress", "done"])
        self.assertTrue(any("Catch" in line for line in self.log()) and any("is growing" in line for line in self.log()))
        self.assertEqual(self.desk.list("done")["count"], 1)

    def test_request_for_something_already_registered_attaches_instead_of_duplicating(self) -> None:
        checked = self.desk.check("Lesson service", "Agents need lessons with evidence before building.")
        self.assertEqual(checked["registry"]["candidates"][0]["id"], "2026-01-01-lesson-service")
        with self.assertRaises(CommissionError):
            self.desk.open("Lesson Service", "Same thing again.", "owner")
        opened = self.desk.open("Lessons for agents", "Agents need lessons with evidence.", "owner",
                                existing_entry="2026-01-01-lesson-service")
        self.assertEqual((opened["state"], opened["attached_to_existing"]), ("decided", True))
        self.assertEqual(len(list((self.registry / "entries").glob("*.json"))), 1)
        with self.assertRaises(CommissionError):
            self.desk.decide(opened["id"], "parked", "Not now.", "owner")  # already growing: nothing to decide

    def test_passing_remarks_are_notes_and_mistaken_commissions_can_be_withdrawn(self) -> None:
        noted = self.desk.note("2026-01-01-lesson-service", "Owner mentioned a design studio node in passing.", "agent")
        self.assertFalse(noted["queued_for_owner"])
        self.assertEqual(self.entry("2026-01-01-lesson-service")["notes"][0]["by"], "agent")
        self.assertEqual(self.desk.list()["count"], 0, "a note creates no commission")
        mistaken = self.desk.open("Studio", "Said in passing.", "owner", existing_entry="2026-01-01-lesson-service")
        self.assertIn(f"commission:{mistaken['id']}", self.entry("2026-01-01-lesson-service")["refs"])
        withdrawn = self.desk.withdraw(mistaken["id"], "Opened from a remark, not a request.", "agent")
        self.assertEqual(withdrawn["state"], "withdrawn")
        self.assertNotIn(f"commission:{mistaken['id']}", self.entry("2026-01-01-lesson-service").get("refs", []))
        boot = front_door.bootstrap(self.registry, self.factory, self.network, self.data)
        self.assertEqual(boot["state"]["open_commissions"], [])
        with self.assertRaises(CommissionError):
            self.desk.decide(mistaken["id"], "parked", "x", "owner")
        fresh = self.desk.open("Brand new", "A thing.", "owner")
        self.desk.withdraw(fresh["id"], "Changed my mind.", "agent")
        self.assertEqual(self.entry(fresh["entry_id"])["status"], "caught", "the entry stays; nothing is deleted")

    def test_routed_and_parked_outcomes_record_the_decision(self) -> None:
        routed = self.desk.open("Dark mode", "The tracker needs a dark mode.", "owner", kind="issue")
        with self.assertRaises(CommissionError):
            self.desk.decide(routed["id"], "routed", "Belongs in the tracker.", "owner")  # routed needs a home
        entry = self.desk.decide(routed["id"], "routed", "Belongs in the tracker.", "owner", home="products/tracker")["entry"]
        self.assertEqual((entry["status"], entry["home"]), ("routed", "products/tracker"))
        parked = self.desk.open("Moon base", "A base on the moon.", "owner")
        self.assertEqual(self.desk.decide(parked["id"], "parked", "No room now.", "owner")["entry"]["status"], "parked")
        with self.assertRaises(CommissionError):
            self.desk.decide(parked["id"], "launch", "x", "owner")

    def test_front_door_bootstrap_playbooks_and_cli(self) -> None:
        self.desk.open("Dark mode", "The tracker needs a dark mode.", "owner")
        boot = front_door.bootstrap(self.registry, self.factory, self.network, self.data)
        self.assertIn("The owner decides.", boot["principles"])
        self.assertEqual({p["name"] for p in boot["playbooks"]}, {"idea-triage", "init-seed"})
        self.assertEqual(boot["state"]["open_commissions"][0]["state"], "triage")
        self.assertLess(len(json.dumps(boot)), 6000, "bootstrap stays small")
        self.assertIn("Steps.", front_door.get_playbook("idea-triage", self.registry, self.factory, self.network)["text"])
        with self.assertRaises(ValueError):
            front_door.get_playbook("../secrets", self.registry, self.factory, self.network)
        self.assertIn("unavailable", front_door.ask_lessons(self.network, "anything"))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--factory-root", str(self.factory), "--network-root", str(self.network), "--data-dir", str(self.data),
                         "commission", "list", "--state", "triage"])
        self.assertEqual((code, json.loads(out.getvalue())["count"]), (0, 1))


if __name__ == "__main__":
    unittest.main()
