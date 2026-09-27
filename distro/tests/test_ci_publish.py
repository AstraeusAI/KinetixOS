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

    def test_ci_publishes_unsigned_and_unprivileged(self):
        self.assertIn("./distro/publish.sh --unsigned", self.wf)
        self.assertIn("secrets.KINETIX_PKGS_DEPLOY_KEY", self.wf)
        self.assertNotIn("secrets.KINETIX_SIGNING_KEY", self.wf)
        self.assertIn("useradd -m builder", self.wf)       # makepkg refuses root

    def test_publish_can_push_through_a_git_remote(self):
        self.assertIn('KINETIX_PKGS_REMOTE', self.publish)
        self.assertIn('git clone --quiet "$PKGS_REMOTE" "$WORK"', self.publish)

    def test_a_failed_package_build_stops_the_publish(self):
        # set -e does not reach into build_package's $(...) caller: the
        # failure must be made explicit, or the repo publishes without it
        self.assertIn('|| die "makepkg failed for $name"', self.publish)

    def test_unsigned_repo_does_not_ship_the_keyring(self):
        self.assertIn('if (( ! UNSIGNED )); then\n    step "Building kinetix-keyring', self.publish)

    def test_publishes_never_overlap(self):
        self.assertIn("cancel-in-progress: false", self.wf)


if __name__ == "__main__":
    unittest.main()


class IsoBuildPacmanConfTests(unittest.TestCase):
    def test_build_time_pacman_conf_drops_the_image_only_kinetix_repo(self):
        # the [kinetix] mirrorlist exists only inside the image; the build host
        # cannot parse a pacman.conf that includes it (build failed on this)
        build = (ROOT / "distro/build-iso.sh").read_text()
        self.assertIn(r"/^\[kinetix\]/{skip=1; next}", build)
        self.assertIn('"$PROFILE/airootfs/usr/share/kinetix/config/pacman.conf"', build)
