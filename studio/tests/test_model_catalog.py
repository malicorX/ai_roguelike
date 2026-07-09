import unittest
import unittest.mock
from studio.config import prefer_nvidia_models
from studio.model_catalog import (
    LOCAL_DEVELOPER_CHAIN,
    NVIDIA_STUDIO_CHAIN,
    endpoint_for_assignment,
    failover_chain_for_role,
    is_nvidia_model_id,
)


class ModelCatalogTest(unittest.TestCase):
    def test_is_nvidia_model_id_detects_provider_style_ids(self) -> None:
        self.assertTrue(is_nvidia_model_id("meta/llama-3.3-70b-instruct"))
        self.assertTrue(is_nvidia_model_id("nvidia:nvidia/nemotron-3-nano-30b-a3b"))
        self.assertFalse(is_nvidia_model_id("hf.co/InternScience/Agents-A1-Q4_K_M-GGUF:latest"))
        self.assertFalse(is_nvidia_model_id("qwen3:14b"))

    def test_failover_chain_puts_assigned_model_first(self) -> None:
        chain = failover_chain_for_role(
            "director",
            assigned_model="meta/llama-3.3-70b-instruct",
            prefer_nvidia=True,
        )
        self.assertEqual(chain[0].model, "meta/llama-3.3-70b-instruct")
        self.assertEqual(chain[0].provider, "nvidia_nim")

    def test_failover_chain_includes_nvidia_and_local_backups(self) -> None:
        chain = failover_chain_for_role("builder", prefer_nvidia=True)
        providers = {endpoint.provider for endpoint in chain}
        models = {endpoint.model for endpoint in chain}
        self.assertIn("nvidia_nim", providers)
        self.assertIn("ollama", providers)
        self.assertIn(NVIDIA_STUDIO_CHAIN[1].model, models)
        self.assertIn(LOCAL_DEVELOPER_CHAIN[0].model, models)

    def test_evaluation_roles_use_sparky2_base_url(self) -> None:
        endpoint = endpoint_for_assignment("qwen3:14b", role="player")
        self.assertIn("sparky2", endpoint.base_url)

    def test_prefer_nvidia_models_honors_env_override(self) -> None:
        with unittest.mock.patch.dict("os.environ", {"STUDIO_PREFER_NVIDIA": "local-only"}, clear=False):
            self.assertFalse(prefer_nvidia_models())
        with unittest.mock.patch.dict("os.environ", {"STUDIO_PREFER_NVIDIA": "nvidia-first"}, clear=False):
            self.assertTrue(prefer_nvidia_models())


if __name__ == "__main__":
    unittest.main()
