import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio.evaluation_client import EvaluationTarget
from studio.config import StudioConfig
from studio.orchestrator import (
    DirectorMode,
    blocked_cycle_for_retry,
    build_evaluation_request,
    clear_cycle_for_retry,
    cycle_is_green,
    main,
    next_cycle_number,
    next_cycle_number_until_green,
    run_dry_cycle,
    run_pilot_cycle,
)
from studio.orchestrator import PilotCycleResult


class OrchestratorTest(unittest.TestCase):
    def _default_designer_output(self) -> str:
        return "\n".join(
            [
                "## Summary",
                "Implement the director objective within known paths.",
                "",
                "## Acceptance criteria",
                "1. Existing npm test and smoke gates remain green.",
                "2. Change matches the objective.",
                "",
                "## In-scope files",
                "- `game/src/main.ts`",
                "",
                "## Test plan",
                "- npm test",
            ]
        )

    def _pass_reviewer_output(self) -> str:
        return "PASS"

    def test_director_context_includes_write_mode_rules(self) -> None:
        from studio.orchestrator import _director_context

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            state_dir.mkdir(parents=True)

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234"]
                context = _director_context(
                    repo,
                    state_dir,
                    5,
                    objective="Fallback",
                    spec="Fallback spec",
                    apply_writes=True,
                )

        self.assertIn("Write-mode rules", context)
        self.assertIn("specialist proposal", context)
        self.assertIn("numeric-only stat tweaks", context)

    def test_write_cycle_runs_specialist_proposals_before_director(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            roles_dir.mkdir(parents=True)
            game = repo / "game"
            game.mkdir(parents=True)
            self._write_success_npm(game)
            for role in ["enemy_designer", "systems_designer", "art_director_concept", "qa_critic"]:
                (roles_dir / f"{role}.md").write_text(f"# {role}\n", encoding="utf-8")

            calls: list[str] = []
            director_contexts: list[str] = []
            specialist_contexts: list[str] = []
            art_contexts: list[str] = []

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = str(args[2])
                calls.append(role)
                if role == "enemy_designer":
                    specialist_contexts.append(str(args[3]))
                    return "\n".join(
                        [
                            "Title: Lantern Leech",
                            "Goal: Add a monster that reacts to light and forces positioning.",
                            "Player experience: The player sees a distinct threat and changes movement.",
                            "Implementation hint: likely game/src/engine.ts and game/src/render.ts.",
                            "Acceptance: Smoke sees a distinct enemy glyph.",
                        ]
                    )
                if role == "systems_designer":
                    return "Title: Echo Step\nGoal: Add noisy movement that attracts danger."
                if role == "art_director_concept":
                    art_contexts.append(str(args[3]))
                    return "Title: Leech Glow\nSupports: enemy_designer-1\nGoal: Use color/glyph contrast for the new enemy."
                if role == "qa_critic":
                    return "Verdict: PASS\n- Lantern Leech has visible behavior and testable acceptance."
                if role == "director":
                    director_contexts.append(str(args[3]))
                    return "Objective: Implement the Lantern Leech enemy concept.\nReason: It was selected by the specialist proposal board."
                if role == "designer":
                    return self._default_designer_output()
                if role == "builder":
                    return "Builder output without patch blocks."
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=7,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model,designer=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                    apply_writes=True,
                )

            self.assertTrue(result.blocked)
            self.assertLess(calls.index("enemy_designer"), calls.index("director"))
            self.assertLess(calls.index("enemy_designer"), calls.index("art_director_concept"))
            self.assertTrue((state_dir / "cycle-0007-proposals.json").is_file())
            self.assertTrue((state_dir / "agent-agendas.json").is_file())
            self.assertIn("Specialist agent agendas", specialist_contexts[0])
            self.assertIn("Primary concepts already proposed", art_contexts[0])
            self.assertIn("Lantern Leech", art_contexts[0])
            self.assertIn("Lantern Leech", director_contexts[0])

    def test_write_cycle_blocks_when_qa_critic_blocks_proposal_board(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            roles_dir.mkdir(parents=True)
            game = repo / "game"
            game.mkdir(parents=True)
            self._write_success_npm(game)
            for role in ["enemy_designer", "qa_critic"]:
                (roles_dir / f"{role}.md").write_text(f"# {role}\n", encoding="utf-8")

            calls: list[str] = []

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = str(args[2])
                calls.append(role)
                if role == "enemy_designer":
                    return "Title: Fog Bat\nGoal: Create a threat."
                if role == "qa_critic":
                    return "Verdict: BLOCK\n- Too vague to test or render."
                if role == "director":
                    raise AssertionError("Director should not run after blocked proposal board")
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=8,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                    apply_writes=True,
                )

            report = json.loads((state_dir / "cycle-0008-report.json").read_text(encoding="utf-8"))
            self.assertTrue(result.blocked)
            self.assertNotIn("director", calls)
            self.assertEqual(report["qa"]["checks"], ["proposal board gate"])

    def test_write_cycle_keeps_proposal_board_when_one_specialist_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            roles_dir.mkdir(parents=True)
            game = repo / "game"
            game.mkdir(parents=True)
            self._write_success_npm(game)
            for role in ["enemy_designer", "systems_designer"]:
                (roles_dir / f"{role}.md").write_text(f"# {role}\n", encoding="utf-8")

            director_contexts: list[str] = []

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = str(args[2])
                if role == "enemy_designer":
                    return "Title: Lantern Leech\nGoal: Create a visible threat."
                if role == "systems_designer":
                    raise TimeoutError("systems model timed out")
                if role == "director":
                    director_contexts.append(str(args[3]))
                    return "Objective: Implement Lantern Leech.\nReason: selected proposal."
                if role == "designer":
                    return self._default_designer_output()
                if role == "builder":
                    return "Builder output without patch blocks."
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=9,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                    apply_writes=True,
                )

            board = json.loads((state_dir / "cycle-0009-proposals.json").read_text(encoding="utf-8"))
            self.assertTrue(result.blocked)
            self.assertEqual(board["selected_id"], "enemy_designer-1")
            self.assertIn("systems model timed out", json.dumps(board))
            self.assertIn("Lantern Leech", director_contexts[0])

    def test_director_context_includes_write_mode_and_recent_cycles(self) -> None:
        from studio.orchestrator import _director_context

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "cycle-0001-director.md").write_text(
                "Objective: Add HUD turn counter.\nReason: readability.\n",
                encoding="utf-8",
            )
            (state_dir / "cycle-0001-reviewer.json").write_text(
                json.dumps({"verdict": "REWORK", "issues": ["Missing test."]}) + "\n",
                encoding="utf-8",
            )

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234"]
                context = _director_context(
                    repo,
                    state_dir,
                    2,
                    objective="Fallback objective",
                    spec="Fallback spec",
                    apply_writes=True,
                )

        self.assertIn("write cycle", context.lower())
        self.assertIn("Cycle 1", context)
        self.assertIn("reviewer=REWORK", context)

    def test_run_pilot_cycle_skips_when_report_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            state_dir.mkdir(parents=True)
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            game.mkdir(parents=True)
            roles_dir.mkdir(parents=True)
            self._write_success_npm(game)
            prefix = "cycle-0099"
            (state_dir / f"{prefix}-director.md").write_text("Objective: Done.\n", encoding="utf-8")
            (state_dir / f"{prefix}-builder.md").write_text("builder\n", encoding="utf-8")
            (state_dir / f"{prefix}-proposal-lint.json").write_text('{"verdict":"PASS","issues":[]}\n', encoding="utf-8")
            (state_dir / f"{prefix}-request.json").write_text("{}\n", encoding="utf-8")
            (state_dir / f"{prefix}-report.json").write_text(
                json.dumps(
                    {
                        "request_branch": "main",
                        "request_commit": "abc1234",
                        "qa": {"verdict": "REWORK", "checks": [], "bugs": ["already done"], "repro_steps": []},
                        "design": {"verdict": "BACKLOG"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            def fail_runner(*_args, **_kwargs) -> str:
                raise AssertionError("role runner should not be called")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=99,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fail_runner,
                )

        self.assertTrue(result.blocked)
        self.assertEqual(result.blocking_reasons, ["QA requested rework."])

    def test_build_evaluation_request_uses_git_identity(self) -> None:
        with patch("studio.orchestrator._git_output") as git_output:
            git_output.side_effect = ["feature/test", "abc1234"]

            request = build_evaluation_request(
                Path("/repo"),
                objective="Keep the v0 game playable",
                spec="Run the current deterministic gates.",
                changed_files=["game/src/main.ts"],
            )

        self.assertEqual(request.branch, "feature/test")
        self.assertEqual(request.commit, "abc1234")
        self.assertEqual(request.seeds, [1, 7, 42])
        self.assertEqual(request.focus, ["qa", "browser-smoke", "visual-readability"])

    def test_dry_cycle_writes_request_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            game = repo / "game"
            game.mkdir(parents=True)
            self._write_success_npm(game)

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234"]
                result = run_dry_cycle(
                    repo,
                    state_dir,
                    objective="Verify current build",
                    spec="Run deterministic local gates.",
                    cycle_number=1,
                    evaluation_target=EvaluationTarget.LOCAL,
                )

            request_data = json.loads(result.request_path.read_text(encoding="utf-8"))
            report_data = json.loads(result.report_path.read_text(encoding="utf-8"))

        self.assertFalse(result.blocked)
        self.assertEqual(request_data["branch"], "main")
        self.assertEqual(report_data["qa"]["verdict"], "PASS")

    def test_dry_cycle_can_use_director_model_output_as_objective(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            game.mkdir(parents=True)
            roles_dir.mkdir(parents=True)
            self._write_success_npm(game)

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_dry_cycle(
                    repo,
                    state_dir,
                    cycle_number=2,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model"),
                    roles_dir=roles_dir,
                    role_runner=lambda *_args, **_kwargs: "Improve visual clarity.\nReason: current v0 needs stronger readability.",
                )

            request_data = json.loads(result.request_path.read_text(encoding="utf-8"))
            director_output = (state_dir / "cycle-0002-director.md").read_text(encoding="utf-8")

        self.assertFalse(result.blocked)
        self.assertEqual(request_data["objective"], "Improve visual clarity.")
        self.assertIn("Reason: current v0 needs stronger readability.", director_output)

    def test_pilot_cycle_records_director_and_builder_artifacts_before_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            src = game / "src"
            game.mkdir(parents=True)
            src.mkdir()
            (game / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest run", "smoke": "npm run build && playwright test"}}),
                encoding="utf-8",
            )
            (src / "main.ts").write_text("export {};\n", encoding="utf-8")
            roles_dir.mkdir(parents=True)
            self._write_success_npm(game)
            builder_contexts: list[str] = []

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Add a visible restart affordance.\nReason: death recovery should be obvious."
                if role == "designer":
                    return self._default_designer_output()
                if role == "builder":
                    builder_contexts.append(str(args[3]))
                    return "Implementation summary: no-write pilot proposal.\nChanged files: none.\nTests: not run by builder."
                if role == "reviewer":
                    return self._pass_reviewer_output()
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=3,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model,designer=test-model,reviewer=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                )

            request_data = json.loads(result.request_path.read_text(encoding="utf-8"))
            director_output = result.director_path.read_text(encoding="utf-8")
            builder_output = result.builder_path.read_text(encoding="utf-8")

        self.assertFalse(result.blocked)
        self.assertEqual(request_data["objective"], "Add a visible restart affordance.")
        self.assertIn("death recovery should be obvious", director_output)
        self.assertIn("no-write pilot proposal", builder_output)
        self.assertIn("Phase 1 pilot", request_data["spec"])
        self.assertIn("game/src/main.ts", builder_contexts[0])
        self.assertIn("Do not invent paths", builder_contexts[0])
        self.assertIn("Do not claim tests were run", builder_contexts[0])
        self.assertIn("npm test", builder_contexts[0])
        self.assertIn("npm run smoke", builder_contexts[0])
        self.assertIn("Designer spec", builder_contexts[0])

    def test_pilot_cycle_blocks_reviewer_rework_before_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            src = game / "src"
            src.mkdir(parents=True)
            (src / "render.ts").write_text("export {};\n", encoding="utf-8")
            (game / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8")
            roles_dir.mkdir(parents=True)
            self._write_success_npm(game)

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Add HUD turn counter."
                if role == "designer":
                    return self._default_designer_output()
                if role == "builder":
                    return "\n".join(
                        [
                            "Implementation summary: add turn counter.",
                            "Proposed changed files:",
                            "- `game/src/render.ts`",
                            "Recommended Test Commands:",
                            "- `npm test`",
                        ]
                    )
                if role == "reviewer":
                    return "REWORK\n1. Builder did not address acceptance criterion 2."
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output, patch("studio.orchestrator.EvaluationClient") as evaluation_client:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=12,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model,designer=test-model,reviewer=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                )

            reviewer_data = json.loads((state_dir / "cycle-0012-reviewer.json").read_text(encoding="utf-8"))
            report_data = json.loads(result.report_path.read_text(encoding="utf-8"))

        self.assertTrue(result.blocked)
        self.assertIn("Reviewer requested rework.", result.blocking_reasons)
        self.assertEqual(reviewer_data["verdict"], "REWORK")
        self.assertEqual(report_data["qa"]["verdict"], "REWORK")
        self.assertEqual(report_data["qa"]["checks"], ["reviewer gate"])
        evaluation_client.assert_not_called()

    def test_pilot_cycle_blocks_invalid_builder_proposal_before_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            game.mkdir(parents=True)
            roles_dir.mkdir(parents=True)
            self._write_success_npm(game)

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Improve movement observability."
                if role == "designer":
                    return self._default_designer_output()
                if role == "builder":
                    return "\n".join(
                        [
                            "Implementation summary: add movement logs.",
                            "Proposed changed files:",
                            "- `src/controllers/PlayerMovementController.js`",
                            "Test Commands Run:",
                            "npm test",
                        ]
                    )
                if role == "reviewer":
                    return self._pass_reviewer_output()
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output, patch("studio.orchestrator.EvaluationClient") as evaluation_client:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=5,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model,designer=test-model,reviewer=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                )

            lint_data = json.loads(result.proposal_lint_path.read_text(encoding="utf-8"))
            report_data = json.loads(result.report_path.read_text(encoding="utf-8"))

        self.assertTrue(result.blocked)
        self.assertIn("Builder proposal lint failed.", result.blocking_reasons)
        self.assertGreaterEqual(len(lint_data["issues"]), 2)
        self.assertEqual(report_data["qa"]["verdict"], "REWORK")
        evaluation_client.assert_not_called()

    def test_pilot_cycle_allows_backticked_test_commands_with_real_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            tests = game / "tests"
            src = game / "src"
            tests.mkdir(parents=True)
            src.mkdir()
            (game / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8")
            (tests / "engine.test.ts").write_text("export {};\n", encoding="utf-8")
            (src / "engine.ts").write_text("export {};\n", encoding="utf-8")
            roles_dir.mkdir(parents=True)
            self._write_success_npm(game)

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Add movement observability."
                if role == "designer":
                    return self._default_designer_output()
                if role == "builder":
                    return "\n".join(
                        [
                            "Implementation summary: add debug logging.",
                            "Proposed changed files:",
                            "- `game/src/engine.ts`",
                            "Recommended Test Commands:",
                            "- `npm test -- game/tests/engine.test.ts`",
                        ]
                    )
                if role == "reviewer":
                    return self._pass_reviewer_output()
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=6,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model,designer=test-model,reviewer=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                )

            lint_data = json.loads(result.proposal_lint_path.read_text(encoding="utf-8"))

        self.assertFalse(result.blocked)
        self.assertEqual(lint_data["verdict"], "PASS")

    def test_pilot_cycle_allows_markdown_list_backticked_npm_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            smoke = game / "smoke"
            src = game / "src"
            smoke.mkdir(parents=True)
            src.mkdir()
            (game / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest run", "smoke": "playwright test"}}),
                encoding="utf-8",
            )
            (src / "render.ts").write_text("export {};\n", encoding="utf-8")
            (smoke / "playability.spec.ts").write_text("export {};\n", encoding="utf-8")
            roles_dir.mkdir(parents=True)
            self._write_success_npm(game)

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Improve smoke failure logging."
                if role == "designer":
                    return self._default_designer_output()
                if role == "builder":
                    return "\n".join(
                        [
                            "Implementation summary: add smoke failure logs.",
                            "Proposed changed files:",
                            "- `game/smoke/playability.spec.ts`",
                            "Recommended Test Commands:",
                            "- `npm run smoke`",
                            "- `npm test`",
                        ]
                    )
                if role == "reviewer":
                    return self._pass_reviewer_output()
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=8,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model,designer=test-model,reviewer=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                )

            lint_data = json.loads(result.proposal_lint_path.read_text(encoding="utf-8"))

        self.assertFalse(result.blocked)
        self.assertEqual(lint_data["verdict"], "PASS")
        self.assertEqual(lint_data["issues"], [])

    def test_pilot_cycle_allows_backticked_npm_commands_with_trailing_colons(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            smoke = game / "smoke"
            smoke.mkdir(parents=True)
            (game / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest run", "smoke": "playwright test"}}),
                encoding="utf-8",
            )
            (smoke / "screenshot-baselines.spec.ts").write_text("export {};\n", encoding="utf-8")
            roles_dir.mkdir(parents=True)
            self._write_success_npm(game)

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Add screenshot baselines."
                if role == "designer":
                    return self._default_designer_output()
                if role == "builder":
                    return "\n".join(
                        [
                            "Created placeholder files at `game/tests/baselines/main_menu.png`.",
                            "Helpers live in `../src/testHarness`.",
                            "Proposed changed files:",
                            "1. `game/smoke/screenshot-baselines.spec.ts` (Modified)",
                            "2. `game/tests/baselines/main_menu.png` (New)",
                            "Recommended Test Commands:",
                            "- `npm run smoke`: Run visual regression tests.",
                            "- `npm test`: Verify TypeScript coverage.",
                        ]
                    )
                if role == "reviewer":
                    return self._pass_reviewer_output()
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=12,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model,designer=test-model,reviewer=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                )

            lint_data = json.loads(result.proposal_lint_path.read_text(encoding="utf-8"))

        self.assertFalse(result.blocked)
        self.assertEqual(lint_data["verdict"], "PASS")
        self.assertEqual(lint_data["issues"], [])

    def test_pilot_cycle_allows_directory_mentions_in_builder_prose(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            smoke = game / "smoke"
            smoke.mkdir(parents=True)
            (game / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run", "smoke": "playwright test"}}), encoding="utf-8")
            roles_dir.mkdir(parents=True)
            self._write_success_npm(game)

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Add canvas render smoke."
                if role == "designer":
                    return self._default_designer_output()
                if role == "builder":
                    return "\n".join(
                        [
                            "Implementation summary: add smoke spec.",
                            "Mention directory `game/smoke/` in prose.",
                            "Proposed changed files:",
                            "- `game/smoke/canvas-render.spec.ts` NEW",
                            "Recommended Test Commands:",
                            "- `npm run smoke`",
                        ]
                    )
                if role == "reviewer":
                    return self._pass_reviewer_output()
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=11,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model,designer=test-model,reviewer=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                )

            lint_data = json.loads(result.proposal_lint_path.read_text(encoding="utf-8"))

        self.assertFalse(result.blocked)
        self.assertEqual(lint_data["verdict"], "PASS")

    def test_pilot_cycle_blocks_unknown_test_commands_before_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            src = game / "src"
            src.mkdir(parents=True)
            (src / "render.ts").write_text("export {};\n", encoding="utf-8")
            (game / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run", "smoke": "playwright test"}}), encoding="utf-8")
            roles_dir.mkdir(parents=True)
            self._write_success_npm(game)

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Add debug overlay proposal."
                if role == "designer":
                    return self._default_designer_output()
                if role == "builder":
                    return "\n".join(
                        [
                            "Implementation summary: add debug overlay.",
                            "Proposed changed files:",
                            "- `game/src/render.ts`",
                            "Recommended Test Commands:",
                            "npx jest game/tests/render.test.ts",
                            "npm run test:smoke --game/smoke/visual-readability.spec.ts",
                        ]
                    )
                if role == "reviewer":
                    return self._pass_reviewer_output()
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output, patch("studio.orchestrator.EvaluationClient") as evaluation_client:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=7,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model,designer=test-model,reviewer=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                )

            lint_data = json.loads(result.proposal_lint_path.read_text(encoding="utf-8"))

        self.assertTrue(result.blocked)
        self.assertIn("Builder proposal lint failed.", result.blocking_reasons)
        self.assertIn("Unsupported npx command: npx jest", lint_data["issues"])
        self.assertIn("Unknown npm script in Builder proposal: test:smoke", lint_data["issues"])
        evaluation_client.assert_not_called()

    def test_static_pilot_cycle_does_not_call_role_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            game = repo / "game"
            game.mkdir(parents=True)
            self._write_success_npm(game)

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=4,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.STATIC,
                    role_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("role runner should not be called")),
                )

            request_data = json.loads(result.request_path.read_text(encoding="utf-8"))
            builder_output = result.builder_path.read_text(encoding="utf-8")

        self.assertFalse(result.blocked)
        self.assertEqual(request_data["objective"], "Verify that the current v0 game remains playable.")
        self.assertIn("no-write static pilot", builder_output)

    def test_main_runs_pilot_loop_when_not_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"

            with patch("studio.orchestrator.run_pilot_cycle") as pilot_cycle, patch("studio.orchestrator._finalize_cycle"):
                state_dir.mkdir(parents=True, exist_ok=True)
                pilot_cycle.return_value.blocked = False
                pilot_cycle.return_value.blocking_reasons = []
                pilot_cycle.return_value.report_path = state_dir / "cycle-0001-report.json"
                pilot_cycle.return_value.director_path = state_dir / "cycle-0001-director.md"
                exit_code = main(
                    [
                        "--repo-root",
                        str(repo),
                        "--state-dir",
                        str(state_dir),
                        "--max-cycles",
                        "1",
                        "--evaluation-target",
                        "local",
                    ]
                )

        self.assertEqual(exit_code, 0)
        pilot_cycle.assert_called_once()

    def test_main_skips_pilot_loop_when_stop_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "STOP").write_text("stop\n", encoding="utf-8")

            with patch("studio.orchestrator.run_pilot_cycle") as pilot_cycle:
                exit_code = main(
                    [
                        "--repo-root",
                        str(repo),
                        "--state-dir",
                        str(state_dir),
                        "--max-cycles",
                        "1",
                        "--evaluation-target",
                        "local",
                    ]
                )

        self.assertEqual(exit_code, 0)
        pilot_cycle.assert_not_called()

    def test_next_cycle_number_resumes_only_latest_incomplete_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            (state_dir / "cycle-0010-director.md").write_text("Objective: old orphan\n", encoding="utf-8")
            (state_dir / "cycle-0030-director.md").write_text("Objective: recent\n", encoding="utf-8")
            (state_dir / "cycle-0031-director.md").write_text("Objective: done\n", encoding="utf-8")
            (state_dir / "cycle-0031-report.json").write_text("{}\n", encoding="utf-8")

            self.assertEqual(next_cycle_number(state_dir), 32)

    def test_next_cycle_number_resumes_latest_when_it_has_no_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            (state_dir / "cycle-0010-director.md").write_text("Objective: old orphan\n", encoding="utf-8")
            (state_dir / "cycle-0030-director.md").write_text("Objective: recent\n", encoding="utf-8")
            (state_dir / "cycle-0031-director.md").write_text("Objective: done\n", encoding="utf-8")
            (state_dir / "cycle-0031-report.json").write_text("{}\n", encoding="utf-8")

            (state_dir / "cycle-0032-director.md").write_text("Objective: in flight\n", encoding="utf-8")

            self.assertEqual(next_cycle_number(state_dir), 32)

    def test_next_cycle_number_resumes_first_incomplete_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            (state_dir / "cycle-0003-director.md").write_text("Objective: test\n", encoding="utf-8")

            self.assertEqual(next_cycle_number(state_dir), 3)

    def test_next_cycle_number_advances_after_report_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            (state_dir / "cycle-0003-director.md").write_text("Objective: test\n", encoding="utf-8")
            (state_dir / "cycle-0003-report.json").write_text("{}\n", encoding="utf-8")

            self.assertEqual(next_cycle_number(state_dir), 4)

    def test_next_cycle_number_advances_after_proposal_only_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            (state_dir / "cycle-0083-director.md").write_text("Objective: test\n", encoding="utf-8")
            (state_dir / "cycle-0083-report.json").write_text("{}\n", encoding="utf-8")
            (state_dir / "cycle-0084-proposals.json").write_text(
                json.dumps({"cycle_number": 84, "selected_id": "enemy_designer-1"}),
                encoding="utf-8",
            )

            self.assertEqual(next_cycle_number(state_dir), 85)

    def test_next_cycle_number_advances_after_proposal_only_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            (state_dir / "cycle-0083-director.md").write_text("Objective: test\n", encoding="utf-8")
            (state_dir / "cycle-0083-report.json").write_text("{}\n", encoding="utf-8")
            (state_dir / "cycle-0084-proposals.json").write_text(
                json.dumps({"cycle_number": 84, "selected_id": "enemy_designer-1"}),
                encoding="utf-8",
            )

            self.assertEqual(next_cycle_number(state_dir), 85)

    def test_blocked_cycle_for_retry_returns_latest_blocked_report_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            (state_dir / "cycle-0088-report.json").write_text(
                json.dumps(
                    {
                        "request_branch": "main",
                        "request_commit": "abc1234",
                        "qa": {"verdict": "REWORK", "bugs": ["patch failed"]},
                        "design": {"verdict": "BACKLOG"},
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(blocked_cycle_for_retry(state_dir), 88)
            self.assertEqual(next_cycle_number_until_green(state_dir, until_green=True), 88)

    def test_clear_cycle_for_retry_removes_gate_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            prefix = state_dir / "cycle-0088"
            (Path(f"{prefix}-report.json")).write_text("{}\n", encoding="utf-8")
            (Path(f"{prefix}-builder.md")).write_text("builder\n", encoding="utf-8")

            cleared = clear_cycle_for_retry(state_dir, 88)

            self.assertIn("report.json", cleared)
            self.assertFalse((state_dir / "cycle-0088-report.json").is_file())

    def test_cycle_is_green_requires_merge_for_apply_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            merge_path = state_dir / "cycle-0005-merge.json"
            merge_path.write_text(json.dumps({"verdict": "MERGED"}) + "\n", encoding="utf-8")
            result = PilotCycleResult(
                director_path=state_dir / "cycle-0005-director.md",
                builder_path=state_dir / "cycle-0005-builder.md",
                proposal_lint_path=state_dir / "cycle-0005-proposal-lint.json",
                request_path=state_dir / "cycle-0005-request.json",
                report_path=state_dir / "cycle-0005-report.json",
                blocked=False,
                blocking_reasons=[],
                merge_path=merge_path,
            )

            self.assertTrue(cycle_is_green(result, apply_writes=True))

    def test_main_until_green_retries_blocked_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            state_dir.mkdir(parents=True)
            blocked = PilotCycleResult(
                director_path=state_dir / "cycle-0001-director.md",
                builder_path=state_dir / "cycle-0001-builder.md",
                proposal_lint_path=state_dir / "cycle-0001-proposal-lint.json",
                request_path=state_dir / "cycle-0001-request.json",
                report_path=state_dir / "cycle-0001-report.json",
                blocked=True,
                blocking_reasons=["patch failed"],
            )
            green_merge = state_dir / "cycle-0001-merge.json"
            green = PilotCycleResult(
                director_path=state_dir / "cycle-0001-director.md",
                builder_path=state_dir / "cycle-0001-builder.md",
                proposal_lint_path=state_dir / "cycle-0001-proposal-lint.json",
                request_path=state_dir / "cycle-0001-request.json",
                report_path=state_dir / "cycle-0001-report.json",
                blocked=False,
                blocking_reasons=[],
                merge_path=green_merge,
            )
            green_merge.write_text(json.dumps({"verdict": "MERGED"}) + "\n", encoding="utf-8")

            with patch("studio.orchestrator.run_pilot_cycle", side_effect=[blocked, green]), patch(
                "studio.orchestrator._finalize_cycle"
            ), patch("studio.orchestrator._publish_devlog"), patch(
                "studio.orchestrator._emit_cycle_process_report"
            ):
                exit_code = main(
                    [
                        "--repo-root",
                        str(repo),
                        "--state-dir",
                        str(state_dir),
                        "--apply-writes",
                        "--until-green",
                        "--evaluation-target",
                        "local",
                    ]
                )

        self.assertEqual(exit_code, 0)

    def test_objective_from_director_output_strips_markdown_bold(self) -> None:
        from studio.orchestrator import _objective_from_director_output

        objective = _objective_from_director_output("**Objective:** Add HUD turn counter.\n**Reason:** readability\n")

        self.assertEqual(objective, "Add HUD turn counter.")

    def test_next_cycle_number_starts_at_one_for_empty_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(next_cycle_number(Path(tmpdir)), 1)

    def test_next_cycle_number_starts_after_latest_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            (state_dir / "cycle-0003-director.md").write_text("Objective: test\n", encoding="utf-8")
            (state_dir / "cycle-0003-report.json").write_text("{}\n", encoding="utf-8")

            self.assertEqual(next_cycle_number(state_dir), 4)

    def test_main_continues_cycle_number_from_existing_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "cycle-0002-director.md").write_text("Objective: test\n", encoding="utf-8")

            with patch("studio.orchestrator.run_pilot_cycle") as pilot_cycle, patch("studio.orchestrator._finalize_cycle"):
                pilot_cycle.return_value.blocked = False
                pilot_cycle.return_value.blocking_reasons = []
                pilot_cycle.return_value.report_path = state_dir / "cycle-0003-report.json"
                pilot_cycle.return_value.director_path = state_dir / "cycle-0003-director.md"
                exit_code = main(
                    [
                        "--repo-root",
                        str(repo),
                        "--state-dir",
                        str(state_dir),
                        "--max-cycles",
                        "1",
                        "--evaluation-target",
                        "local",
                    ]
                )

        self.assertEqual(exit_code, 0)
        pilot_cycle.assert_called_once()
        self.assertEqual(pilot_cycle.call_args.kwargs["cycle_number"], 2)

    def test_write_cycle_blocks_when_builder_output_has_no_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            src = game / "src"
            src.mkdir(parents=True)
            (game / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8")
            (src / "render.ts").write_text("export {};\n", encoding="utf-8")
            roles_dir.mkdir(parents=True)
            self._init_git_repo(repo)
            self._write_success_npm(game)

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Add HUD turn counter."
                if role == "designer":
                    return self._default_designer_output()
                if role == "builder":
                    return "Implementation summary: forgot the diff."
                if role == "reviewer":
                    return self._pass_reviewer_output()
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=9,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model,designer=test-model,reviewer=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                    apply_writes=True,
                )

            report_data = json.loads(result.report_path.read_text(encoding="utf-8"))

        self.assertTrue(result.blocked)
        self.assertIn("Builder output did not include a unified diff fenced block.", result.blocking_reasons)
        self.assertEqual(report_data["qa"]["verdict"], "REWORK")
        self.assertEqual(report_data["qa"]["checks"], ["builder role"])

    def test_write_cycle_blocks_when_builder_output_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            src = game / "src"
            src.mkdir(parents=True)
            (game / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8")
            (src / "render.ts").write_text("export {};\n", encoding="utf-8")
            roles_dir.mkdir(parents=True)
            self._init_git_repo(repo)
            self._write_success_npm(game)

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Add HUD turn counter."
                if role == "designer":
                    return self._default_designer_output()
                if role == "builder":
                    return "   "
                if role == "reviewer":
                    return self._pass_reviewer_output()
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=10,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model,designer=test-model,reviewer=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                    apply_writes=True,
                )

            report_data = json.loads(result.report_path.read_text(encoding="utf-8"))

        self.assertTrue(result.blocked)
        self.assertIn("Builder returned empty output in write mode.", result.blocking_reasons)
        self.assertEqual(report_data["qa"]["checks"], ["builder role"])

    def test_write_cycle_blocks_verification_only_director_objective(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            game.mkdir(parents=True)
            (game / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8")
            roles_dir.mkdir(parents=True)
            self._init_git_repo(repo)
            self._write_success_npm(game)

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Verify that the current v0 game remains playable.\nReason: safety check."
                raise AssertionError(f"Unexpected role after director gate: {role}")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=11,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model,designer=test-model,reviewer=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                    apply_writes=True,
                )

            report_data = json.loads(result.report_path.read_text(encoding="utf-8"))

        self.assertTrue(result.blocked)
        self.assertIn("Director picked a verification-only objective in write mode.", result.blocking_reasons)
        self.assertEqual(report_data["qa"]["checks"], ["director objective gate"])

    def test_write_cycle_blocks_test_only_director_objective_when_churn_guard_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            game.mkdir(parents=True)
            (game / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8")
            roles_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True, exist_ok=True)
            self._init_git_repo(repo)
            self._write_success_npm(game)
            (state_dir / "cycle-0070-merge.json").write_text(
                json.dumps({"verdict": "MERGED", "branch": "test", "commit": "abc1234"}) + "\n",
                encoding="utf-8",
            )
            (state_dir / "cycle-0070-apply.json").write_text(
                json.dumps({"changed_files": ["game/tests/player_health.test.ts"], "verdict": "APPLIED"}) + "\n",
                encoding="utf-8",
            )

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Add unit test for win condition in game/tests/win_condition.test.ts\nReason: coverage"
                raise AssertionError(f"Unexpected role after churn gate: {role}")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=71,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model,designer=test-model,reviewer=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                    apply_writes=True,
                )

            report_data = json.loads(result.report_path.read_text(encoding="utf-8"))

        self.assertTrue(result.blocked)
        self.assertIn("test-only objective", result.blocking_reasons[1].lower())
        self.assertEqual(report_data["qa"]["checks"], ["gameplay churn gate"])

    def test_write_cycle_blocks_verification_only_designer_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            game.mkdir(parents=True)
            (game / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8")
            roles_dir.mkdir(parents=True)
            self._init_git_repo(repo)
            self._write_success_npm(game)

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Add combat damage unit test.\nReason: logic coverage."
                if role == "designer":
                    return "\n".join(
                        [
                            "1. **Summary** — Establish a verification baseline ensuring existing tests pass.",
                            "2. **Acceptance criteria** — npm test passes.",
                            "3. **In-scope files** — game/smoke/playable.spec.ts",
                            "4. **Out of scope** — No new gameplay mechanics.",
                            "5. **Test plan** — npm test",
                        ]
                    )
                raise AssertionError(f"Unexpected role after designer gate: {role}")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=12,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model,designer=test-model,reviewer=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                    apply_writes=True,
                )

            report_data = json.loads(result.report_path.read_text(encoding="utf-8"))

        self.assertTrue(result.blocked)
        self.assertIn("Designer spec rejected in write mode.", result.blocking_reasons)
        self.assertEqual(report_data["qa"]["checks"], ["designer spec gate"])

    def test_builder_role_timeout_writes_blocked_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            game.mkdir(parents=True)
            self._write_success_npm(game)
            roles_dir.mkdir(parents=True)
            self._init_git_repo(repo)

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Add movement bounds test."
                if role == "designer":
                    return self._default_designer_output()
                if role == "builder":
                    raise TimeoutError("timed out")
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=10,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model,designer=test-model,reviewer=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                    apply_writes=True,
                )

            report_data = json.loads(result.report_path.read_text(encoding="utf-8"))

        self.assertTrue(result.blocked)
        self.assertIn("Builder role failed.", result.blocking_reasons)
        self.assertEqual(report_data["qa"]["checks"], ["builder role"])

    def test_write_cycle_applies_diff_merges_on_green_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            src = game / "src"
            src.mkdir(parents=True)
            (game / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8")
            (src / "render.ts").write_text("export const label = 'play';\n", encoding="utf-8")
            roles_dir.mkdir(parents=True)
            self._init_git_repo(repo)
            self._write_success_npm(game)

            builder_output = "\n".join(
                [
                    "Implementation summary: update render label.",
                    "Proposed changed files:",
                    "- `game/src/render.ts`",
                    "```search_replace game/src/render.ts",
                    "<<<<<<< SEARCH",
                    "export const label = 'play';",
                    "=======",
                    "export const label = 'play-updated';",
                    ">>>>>>> REPLACE",
                    "```",
                ]
            )

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Update render label."
                if role == "designer":
                    return "\n".join(
                        [
                            "## Summary",
                            "Update render label.",
                            "",
                            "## In-scope files",
                            "- `game/src/render.ts`",
                        ]
                    )
                if role == "builder":
                    return builder_output
                if role == "reviewer":
                    return self._pass_reviewer_output()
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output, patch("studio.orchestrator.push_main"), patch(
                "studio.orchestrator.EvaluationClient"
            ) as evaluation_client:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                evaluation_client.return_value.evaluate.return_value.blocks_merge.return_value = False
                evaluation_client.return_value.evaluate.return_value.blocking_reasons.return_value = []
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=10,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model,designer=test-model,reviewer=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                    apply_writes=True,
                )

            apply_data = json.loads(result.apply_path.read_text(encoding="utf-8"))
            merge_data = json.loads(result.merge_path.read_text(encoding="utf-8"))
            render_source = (src / "render.ts").read_text(encoding="utf-8")

        self.assertFalse(result.blocked)
        self.assertEqual(apply_data["verdict"], "APPLIED")
        self.assertEqual(merge_data["verdict"], "MERGED")
        self.assertIn("play-updated", render_source)

    def test_write_cycle_merges_supported_specialist_concept_on_green_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            src = game / "src"
            src.mkdir(parents=True)
            (game / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8")
            (src / "engine.ts").write_text(
                "\n".join(
                    [
                        "export type Enemy = { id: string; glyph: string };",
                        "export function createEnemies(): Enemy[] {",
                        '  return [{ id: "enemy-1", glyph: "e" }];',
                        "}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            roles_dir.mkdir(parents=True)
            for role in ["enemy_designer", "systems_designer", "art_director_concept", "qa_critic"]:
                (roles_dir / f"{role}.md").write_text(f"# {role}\n", encoding="utf-8")
            self._init_git_repo(repo)
            self._write_success_npm(game)

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = str(args[2])
                if role == "enemy_designer":
                    return "\n".join(
                        [
                            "Title: Lantern Leech",
                            "Goal: Add a distinct enemy identity for future light-hunting behavior.",
                            "Player experience: The player sees a new threatening glyph.",
                            "Implementation hint: Update game/src/engine.ts enemy spawn data.",
                            "Acceptance: createEnemies includes enemy-2 with glyph L.",
                        ]
                    )
                if role == "systems_designer":
                    return "Title: Echo Step\nGoal: Add movement noise pressure later."
                if role == "art_director_concept":
                    return "Title: Leech Glyph\nSupports: enemy_designer-1\nGoal: Use glyph L for the leech."
                if role == "qa_critic":
                    return "Verdict: PASS\n- Concept has visible identity and deterministic acceptance."
                if role == "director":
                    return "Proposal: enemy_designer-1\nObjective: Implement the Lantern Leech enemy data.\nReason: It has art support and QA acceptance."
                if role == "designer":
                    return "\n".join(
                        [
                            "## Summary",
                            "Add Lantern Leech enemy data.",
                            "",
                            "## Acceptance criteria",
                            "1. createEnemies returns enemy-2 with glyph L.",
                            "",
                            "## In-scope files",
                            "- `game/src/engine.ts`",
                            "",
                            "## Test plan",
                            "- npm test",
                        ]
                    )
                if role == "builder":
                    return "\n".join(
                        [
                            "Implementation summary: add Lantern Leech enemy data.",
                            "Proposed changed files:",
                            "- `game/src/engine.ts`",
                            "```search_replace game/src/engine.ts",
                            "<<<<<<< SEARCH",
                            '  return [{ id: "enemy-1", glyph: "e" }];',
                            "=======",
                            '  return [{ id: "enemy-1", glyph: "e" }, { id: "enemy-2", glyph: "L" }];',
                            ">>>>>>> REPLACE",
                            "```",
                        ]
                    )
                if role == "reviewer":
                    return "PASS"
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output, patch("studio.orchestrator.push_main"), patch(
                "studio.orchestrator.EvaluationClient"
            ) as evaluation_client:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                evaluation_client.return_value.evaluate.return_value.blocks_merge.return_value = False
                evaluation_client.return_value.evaluate.return_value.blocking_reasons.return_value = []
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=12,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model,designer=test-model,reviewer=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                    apply_writes=True,
                )

            board = json.loads((state_dir / "cycle-0012-proposals.json").read_text(encoding="utf-8"))
            engine_source = (src / "engine.ts").read_text(encoding="utf-8")

        self.assertFalse(result.blocked)
        self.assertEqual(board["selected_id"], "enemy_designer-1")
        self.assertIn("art_director_concept-1", json.dumps(board))
        self.assertIn('glyph: "L"', engine_source)

    def test_main_proposal_only_writes_board_without_director(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            roles_dir.mkdir(parents=True)
            for role in ["enemy_designer", "qa_critic"]:
                (roles_dir / f"{role}.md").write_text(f"# {role}\n", encoding="utf-8")

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = str(args[2])
                if role == "enemy_designer":
                    return "Title: Lantern Leech\nGoal: Create a visible threat."
                if role == "qa_critic":
                    return "Verdict: PASS\n- Visible and testable."
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator.run_role", side_effect=fake_role_runner), patch(
                "studio.orchestrator._publish_devlog"
            ):
                exit_code = main(
                    [
                        "--repo-root",
                        str(repo),
                        "--state-dir",
                        str(state_dir),
                        "--director-mode",
                        "model",
                        "--proposal-only",
                        "--max-cycles",
                        "1",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue((state_dir / "cycle-0001-proposals.json").is_file())
            self.assertFalse((state_dir / "cycle-0001-director.md").is_file())

    def test_run_local_game_build_gate_skips_without_node_modules(self) -> None:
        from studio.orchestrator import _run_local_game_build_gate

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            game = repo / "game"
            game.mkdir()
            (game / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}), encoding="utf-8")

            self.assertEqual(_run_local_game_build_gate(repo), [])

    def _init_git_repo(self, repo: Path) -> None:
        import subprocess

        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True, capture_output=True)

    def _write_success_npm(self, game: Path) -> None:
        script = game / ("npm.cmd" if _is_windows() else "npm")
        if _is_windows():
            script.write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")
        else:
            script.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
            script.chmod(0o755)


    def test_source_snippets_includes_full_scoped_file_under_limit(self) -> None:
        from studio.orchestrator import _source_snippets

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            target = repo / "game" / "src" / "main.ts"
            target.parent.mkdir(parents=True)
            lines = [f"const line{i} = {i};" for i in range(123)]
            lines.append('status.textContent = "HP";')
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")

            snippets = _source_snippets(repo, ["game/src/main.ts"], scoped_paths={"game/src/main.ts"})

        self.assertIn('status.textContent = "HP";', snippets)
        self.assertIn(" 124|", snippets)
        self.assertIn("line-number prefixes", snippets)

    def test_source_snippets_uses_head_and_tail_for_large_scoped_file(self) -> None:
        from studio.orchestrator import _source_snippets

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            target = repo / "game" / "src" / "engine.ts"
            target.parent.mkdir(parents=True)
            lines = [f"const line{i} = {i};" for i in range(300)]
            lines[250] = "export function createGame() {"
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")

            snippets = _source_snippets(repo, ["game/src/engine.ts"], scoped_paths={"game/src/engine.ts"})

        self.assertIn("const line0 = 0;", snippets)
        self.assertIn("export function createGame() {", snippets)
        self.assertIn("lines omitted", snippets)


def _is_windows() -> bool:
    return __import__("os").name == "nt"


if __name__ == "__main__":
    unittest.main()
