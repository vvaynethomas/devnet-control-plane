"""Automated verification suite for ART-0007: Development Network Control Plane & Interaction Frame Lab."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from control_plane import DEV_NETWORK_ROOT, FACTORY_ROOT, REGISTRY_PATH
from control_plane.capabilities import discover_capabilities
from control_plane.fabric import FabricIndex, redact_secrets
from control_plane.interaction_lab import InteractionFrameEngine
from control_plane.portfolio import scan_portfolio
from control_plane.queues import aggregate_queues, match_router_route
from control_plane.ui import ControlPlaneWorkbench, serve_control_plane


class TestControlPlaneMVP(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp_dir.name)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_pillar1_portfolio_discovery_and_git_state(self) -> None:
        res = scan_portfolio(DEV_NETWORK_ROOT, FACTORY_ROOT, include_worktrees=False)
        self.assertGreaterEqual(res["summary"]["total_repos"], 1)
        self.assertEqual(res["summary"]["incubated_projects"], 5)
        factory_repos = [r for r in res["repositories"] if r["is_factory"]]
        self.assertEqual(len(factory_repos), 1)
        f_repo = factory_repos[0]
        self.assertTrue(f_repo["git"]["is_git"])
        self.assertTrue(f_repo["git"]["branch"])
        self.assertEqual(f_repo["stewardship"]["stewardship_tier"], "factory-governed")

    def test_pillar2_queues_and_next_action_router(self) -> None:
        q = aggregate_queues(FACTORY_ROOT, DEV_NETWORK_ROOT)
        self.assertGreater(q["summary"]["total_rows"], 50)
        self.assertGreater(q["summary"]["awaiting_acceptance"], 0)
        self.assertGreater(q["summary"]["open"], 0)
        self.assertGreater(len(q["next_actions"]), 0)

        # Verify PAT-0001 data-driven router matching
        m1 = match_router_route("I have a chat transcript and raw notes")
        self.assertTrue(m1["matched"])
        self.assertEqual(m1["route"]["entity_id"], "SKL-0003")

        m2 = match_router_route("test an InteractionFrame affect hypothesis")
        self.assertTrue(m2["matched"])
        self.assertEqual(m2["route"]["entity_id"], "ART-0007")

        m_unknown = match_router_route("completely unknown alien artifact xyz")
        self.assertFalse(m_unknown["matched"])

    def test_pillar3_fabric_fts5_search_and_provenance(self) -> None:
        fabric = FabricIndex(
            db_path=self.data_dir / "test_fabric.sqlite",
            factory_root=FACTORY_ROOT,
        )
        counts = fabric.rebuild(include_conversations=True)
        self.assertGreaterEqual(counts["knowledge_entities"], 80)

        # Search for InteractionFrame
        search_res = fabric.search(query="InteractionFrame", limit=10)
        found_ids = {r["id"] for r in search_res["results"]}
        self.assertIn("SRC-0016", found_ids)
        self.assertIn("DEC-0014", found_ids)

        # Inspect entity provenance chain
        ent = fabric.get_entity("DEC-0014")
        self.assertIsNotNone(ent)
        assert ent is not None
        up_ids = {u["id"] for u in ent["upstream_nodes"]}
        down_ids = {d["id"] for d in ent["downstream_nodes"]}
        self.assertIn("SRC-0016", up_ids)
        self.assertIn("FND-0019", up_ids)
        self.assertIn("ART-0007", down_ids)

        # Verify secret redaction
        redacted = redact_secrets("token is ghp_1234567890abcdefghijklmnopqrstuv and sk-proj1234567890abcdefghijklm")
        self.assertNotIn("ghp_123456", redacted)
        self.assertIn("[REDACTED_SECRET]", redacted)

    def test_pillar4_capability_discovery(self) -> None:
        fabric = FabricIndex(
            db_path=self.data_dir / "test_fabric.sqlite",
            factory_root=FACTORY_ROOT,
        )
        fabric.rebuild(include_conversations=False)
        cap = discover_capabilities("rclone cloud metadata", FACTORY_ROOT, fabric)
        self.assertGreater(cap["summary"]["matching_tools_and_modules"], 0)
        tool_ids = [t["id"] for t in cap["existing_tools_and_modules"]]
        self.assertIn("MOD:rclone", tool_ids)

        cap_pat = discover_capabilities("compression without erasure raw snapshot", FACTORY_ROOT, fabric)
        pat_ids = [p["id"] for p in cap_pat["related_patterns"]]
        self.assertIn("PAT-0002", pat_ids)

    @patch.dict("os.environ", {"OPENAI_API_KEY": ""})
    def test_pillar5_interaction_frame_compiler_and_lab_evaluation(self) -> None:
        engine = InteractionFrameEngine(
            registry_path=REGISTRY_PATH,
            db_path=self.data_dir / "test_lab.sqlite",
        )
        reg = engine.load_registry()
        self.assertGreaterEqual(len(reg["frames"]), 5)

        # Compile cute_mentor_builder vs caveman_principal_peer
        c_cute = engine.compile_frame("How should we structure our repo?", "cute_mentor_builder")
        c_cave = engine.compile_frame("How should we structure our repo?", "caveman_principal_peer")
        self.assertNotEqual(c_cute["manifest_digest"], c_cave["manifest_digest"])
        self.assertIn("Overwhelmed Systems Builder", c_cute["system_prompt"])
        self.assertIn("Why waste time say lot word", c_cave["system_prompt"])

        # Register a new custom frame and verify versioning
        custom = engine.save_custom_frame(
            frame_id="academic_peer_critic",
            title="Academic Peer Critic",
            description="Formal research tone with peer-to-peer adversarial review",
            presentation="academic",
            user_model="researcher",
            assistant_model="critic",
            relationship="peer_peer",
            desired_behaviors=["critique", "research"],
        )
        self.assertTrue(custom["digest"])

        # Execute side-by-side evaluation across 3 frames and persist
        run = engine.run_side_by_side_evaluation(
            task_prompt="Design a benchmark for interaction frames.",
            frame_ids=["baseline_direct", "cute_mentor_builder", "academic_peer_critic"],
            desired_behavior="research",
        )
        self.assertEqual(len(run["variants"]), 3)
        self.assertTrue(run["run_id"].startswith("EVAL-"))

        # Record human rubric score and winner
        scored = engine.record_human_rating(
            run_id=run["run_id"],
            frame_id="cute_mentor_builder",
            usefulness=5,
            actionability=5,
            initiative=5,
            specificity=4,
            winner=True,
        )
        winners = [v["frame_id"] for v in scored["variants"] if v["ratings"]["winner"]]
        self.assertEqual(winners, ["cute_mentor_builder"])

    @patch.dict("os.environ", {"OPENAI_API_KEY": ""})
    def test_web_workbench_rendering_and_endpoints(self) -> None:
        wb = ControlPlaneWorkbench(
            factory_root=FACTORY_ROOT,
            network_root=DEV_NETWORK_ROOT,
            data_dir=self.data_dir,
        )
        wb.fabric.rebuild(include_conversations=False)
        wb.interaction_lab.run_side_by_side_evaluation(
            task_prompt="Test task for workbench rendering",
            frame_ids=["baseline_direct", "cute_mentor_builder", "caveman_principal_peer"],
        )

        p_html = wb.render_portfolio_tab(include_worktrees=False)
        self.assertIn("Incubated Projects", p_html)
        self.assertIn("PRJ-0005", p_html)

        q_html = wb.render_queues_tab(route_query="InteractionFrame eval")
        self.assertIn("Data-Driven Next-Action Router", q_html)
        self.assertIn("ART-0007", q_html)

        f_html = wb.render_fabric_tab(query="InteractionFrame", entity_id="DEC-0014")
        self.assertIn("Provenance &amp; Entity Inspector", f_html)
        self.assertIn("SRC-0016", f_html)

        c_html = wb.render_capabilities_tab(problem_query="sqlite")
        self.assertIn("Have We Solved This Before?", c_html)
        self.assertIn("Do We Already Have a Tool or Code Module for This?", c_html)

        i_html = wb.render_interaction_tab()
        self.assertIn("Side-by-Side Comparison Run", i_html)
        self.assertIn("Guided Mentorship", i_html)



    def test_pillar6_conversations_command_center_and_tokenomics(self) -> None:
        from control_plane.conversations import UnifiedConversationHub

        hub = UnifiedConversationHub(data_dir=self.data_dir, factory_root=FACTORY_ROOT)
        imp = hub.import_external_chat(
            title="Microsoft Copilot Architecture Brainstorm",
            platform="Microsoft Copilot",
            model="GPT-4o (Copilot)",
            raw_text="User: How do we synchronize multi-agent conversations?\n\nCopilot: Use a unified conversation hub with tokenomics tracking.",
            workspace="AIAD-ex12410",
        )
        self.assertTrue(imp["session_id"].startswith("EXT-"))
        self.assertGreater(imp["est_tokens"], 0)

        all_convs = hub.get_all_conversations()
        self.assertGreaterEqual(all_convs["summary"]["total_sessions"], 1)
        self.assertGreater(all_convs["summary"]["est_total_tokens"], 0)
        self.assertIn("Microsoft Copilot", all_convs["summary"]["platforms"])

        wb = ControlPlaneWorkbench(
            factory_root=FACTORY_ROOT,
            network_root=DEV_NETWORK_ROOT,
            data_dir=self.data_dir,
        )
        c_html = wb.render_conversations_tab()
        self.assertIn("Tokenomics", c_html)
        self.assertIn("1-Click Copy Full Handoff Packet", c_html)
        self.assertIn("Copy Turn", c_html)
        self.assertIn("Microsoft Copilot", c_html)


if __name__ == "__main__":
    unittest.main()
