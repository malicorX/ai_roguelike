import tempfile
import unittest
from pathlib import Path

from studio.config import DEFAULT_MODEL, StudioConfig
from studio.role_runner import build_ollama_payload, render_role_prompt


class RoleRunnerTest(unittest.TestCase):
    def test_render_role_prompt_combines_role_file_and_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            roles_dir = Path(tmpdir)
            (roles_dir / "director.md").write_text("Pick the next objective.\n", encoding="utf-8")

            prompt = render_role_prompt(roles_dir, "director", "World state: playable.")

        self.assertIn("Pick the next objective.", prompt)
        self.assertIn("World state: playable.", prompt)

    def test_build_ollama_payload_uses_role_model(self) -> None:
        config = StudioConfig.from_model_string("director=custom-model")

        payload = build_ollama_payload(config, "director", "Prompt")

        self.assertEqual(payload["model"], "custom-model")
        self.assertEqual(payload["stream"], False)
        self.assertEqual(payload["messages"][0]["role"], "user")

    def test_build_ollama_payload_uses_default_model(self) -> None:
        payload = build_ollama_payload(StudioConfig(), "builder", "Prompt")

        self.assertEqual(payload["model"], DEFAULT_MODEL)


if __name__ == "__main__":
    unittest.main()
