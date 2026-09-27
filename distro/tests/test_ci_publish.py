"""Contracts for publishing an update from every commit on `stable`."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CiPublishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wf = (ROOT / ".github/workflows/publish.yml").read_text()
        cls.publish = (ROOT / "distro/publish.sh").read_text()

    def test_publishes_from_the_stable_branch_only(self):
        self.assertIn("branches: [stable]", self.wf)
        self.assertNotIn("branches: [master]", self.wf)

    def test_version_is_derived_from_the_commit(self):
        # <distro/version>.r<commit count>.g<sha>: pacman orders these by count
        self.assertIn('${base}.r${count}.g${sha}', self.wf)
        self.assertIn("fetch-depth: 0", self.wf)
        self.assertIn('pkgver="${KINETIX_PKGVER:-', self.publish)

    def test_tests_gate_the_publish(self):
        self.assertLess(self.wf.index("python3 -m unittest discover -s distro/tests"),
                        self.wf.index("./distro/publish.sh"))

    def test_packages_are_signed_and_built_unprivileged(self):
        for secret in ("KINETIX_SIGNING_KEY", "KINETIX_SIGNING_PASSPHRASE", "KINETIX_PKGS_DEPLOY_KEY"):
            self.assertIn("secrets." + secret, self.wf)
        self.assertIn("useradd -m builder", self.wf)       # makepkg refuses root
        self.assertIn("gpg-preset-passphrase", self.wf)    # signing never prompts in CI

    def test_publish_can_push_through_a_git_remote(self):
        self.assertIn('KINETIX_PKGS_REMOTE', self.publish)
        self.assertIn('git clone --quiet "$PKGS_REMOTE" "$WORK"', self.publish)

    def test_publishes_never_overlap(self):
        self.assertIn("cancel-in-progress: false", self.wf)


if __name__ == "__main__":
    unittest.main()
