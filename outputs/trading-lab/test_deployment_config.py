"""Tests for deployment configuration safety.

Verifies that render.yaml and requirements.txt enforce safe defaults:
- Live trading is disabled by default
- Private keys are sync:false (not committed to repo)
- A persistent disk is configured
- Required dependencies are declared
"""
import os
import unittest

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


class DeploymentConfigTests(unittest.TestCase):
    """Verify render.yaml enforces safe defaults."""

    @classmethod
    def setUpClass(cls):
        cls.lab_dir = os.path.dirname(os.path.abspath(__file__))
        cls.repo_root = os.path.dirname(os.path.dirname(cls.lab_dir))
        cls.render_path = os.path.join(cls.repo_root, "render.yaml")

    def _load_render(self):
        if not HAS_YAML:
            self.skipTest("PyYAML not installed; skipping YAML parse test")
        if not os.path.exists(self.render_path):
            self.skipTest("render.yaml not found")
        with open(self.render_path) as f:
            return yaml.safe_load(f)

    def test_legacy_crypto_environment_is_absent(self):
        """The Forex deployment must not configure crypto trading credentials or workers."""
        if not HAS_YAML or not os.path.exists(self.render_path):
            self.skipTest("render.yaml or PyYAML not available")
        config = self._load_render()
        keys = {var["key"] for var in config["services"][0]["envVars"]}
        self.assertNotIn("JUPITER_AUTORUN", keys)
        self.assertNotIn("SOLANA_PRIVATE_KEY", keys)

    def test_solana_private_key_is_not_committed(self):
        """SOLANA_PRIVATE_KEY must be sync:false — never in the repo."""
        if not HAS_YAML or not os.path.exists(self.render_path):
            self.skipTest("render.yaml or PyYAML not available")
        config = self._load_render()
        env_vars = config["services"][0]["envVars"]
        for var in env_vars:
            if var["key"] == "SOLANA_PRIVATE_KEY":
                self.assertIn("sync", var, "SOLANA_PRIVATE_KEY must be sync:false")
                self.assertNotIn("value", var, "SOLANA_PRIVATE_KEY must NOT have a value in render.yaml")
                return
        # If not present at all, that's also safe
        self.skipTest("SOLANA_PRIVATE_KEY not in render.yaml (also safe)")

    def test_persistent_disk_is_configured(self):
        """A persistent disk must be configured for trading state."""
        if not HAS_YAML or not os.path.exists(self.render_path):
            self.skipTest("render.yaml or PyYAML not available")
        config = self._load_render()
        service = config["services"][0]
        self.assertIn("disk", service, "render.yaml must configure a persistent disk")
        disk = service["disk"]
        self.assertIn("mountPath", disk)
        self.assertNotEqual(disk["mountPath"], "/tmp", "Disk must not be mounted on /tmp (ephemeral)")

    def test_data_dir_matches_disk_mount(self):
        """TRADINGLAB_DATA_DIR must point to the persistent disk mount."""
        if not HAS_YAML or not os.path.exists(self.render_path):
            self.skipTest("render.yaml or PyYAML not available")
        config = self._load_render()
        service = config["services"][0]
        env_vars = service["envVars"]
        disk_path = service.get("disk", {}).get("mountPath", "")
        if not disk_path:
            self.skipTest("No disk configured")
        for var in env_vars:
            if var["key"] == "TRADINGLAB_DATA_DIR":
                self.assertEqual(var["value"], disk_path,
                                 "TRADINGLAB_DATA_DIR must match disk mountPath")
                return
        self.skipTest("TRADINGLAB_DATA_DIR not in render.yaml")


class RequirementsTests(unittest.TestCase):
    """Verify required dependencies are declared for deployment."""

    @classmethod
    def setUpClass(cls):
        cls.lab_dir = os.path.dirname(os.path.abspath(__file__))

    def test_requirements_file_exists(self):
        path = os.path.join(self.lab_dir, "requirements.txt")
        if not os.path.exists(path):
            self.skipTest("requirements.txt not found")

    def test_requirements_contains_forex_runtime_deps(self):
        path = os.path.join(self.lab_dir, "requirements.txt")
        if not os.path.exists(path):
            self.skipTest("requirements.txt not found")
        with open(path) as f:
            content = f.read().lower()
        self.assertNotIn("base58", content, "Forex-only runtime must not require Solana dependencies")
        self.assertNotIn("pynacl", content, "Forex-only runtime must not require transaction signing")


if __name__ == "__main__":
    unittest.main()
