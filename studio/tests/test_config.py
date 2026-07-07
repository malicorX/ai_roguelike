import unittest

from studio.config import DEFAULT_MODEL, StudioConfig, parse_model_assignments


class StudioConfigTest(unittest.TestCase):
    def test_parse_model_assignments_trims_roles_and_models(self) -> None:
        self.assertEqual(
            parse_model_assignments("director=agents-a1, builder = agents-a1 , player=agents-a1"),
            {
                "director": "agents-a1",
                "builder": "agents-a1",
                "player": "agents-a1",
            },
        )

    def test_parse_model_assignments_rejects_malformed_entries(self) -> None:
        with self.assertRaises(ValueError):
            parse_model_assignments("director=agents-a1,builder")

    def test_config_resolves_default_model_and_role_hosts(self) -> None:
        config = StudioConfig.from_model_string("director=custom-director")

        self.assertEqual(config.model_for("director"), "custom-director")
        self.assertEqual(config.model_for("builder"), DEFAULT_MODEL)
        self.assertEqual(config.ollama_base_url_for("director"), "http://127.0.0.1:11434")
        self.assertEqual(config.ollama_base_url_for("player"), "http://sparky2:11435")


if __name__ == "__main__":
    unittest.main()
