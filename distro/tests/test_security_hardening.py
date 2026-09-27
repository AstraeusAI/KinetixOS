"""Round 16: security-review follow-ups for the live session."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
AIROOTFS = ROOT / "distro/archiso/airootfs"


class SudoHardeningTests(unittest.TestCase):
    def test_kinetix_sudo_requires_authentication(self):
        text = (AIROOTFS / "etc/sudoers.d/kinetix-live").read_text()
        self.assertIn("Defaults:kinetix timestamp_timeout=0", text)
        self.assertIn("kinetix ALL=(ALL:ALL) PASSWD: ALL", text)
        self.assertNotIn("NOPASSWD", text)
        self.assertNotIn("requiretty", text)
        self.assertIn("LIVE SESSION ONLY", text)

    def test_live_password_is_established_before_sddm_autologin(self):
        service = (AIROOTFS / "usr/lib/systemd/system/kinetix-live-password.service").read_text()
        script_path = AIROOTFS / "usr/bin/kinetix-live-password"
        script = script_path.read_text()
        builder = (ROOT / "distro/build-iso.sh").read_text()
        self.assertIn("Before=sddm.service", service)
        self.assertIn("TTYPath=/dev/tty1", service)
        self.assertIn("kinetix-live-password.service", builder)
        self.assertTrue(script_path.stat().st_mode & 0o111)
        self.assertIn("read -r -s password", script)
        self.assertIn("chpasswd", script)
        self.assertNotIn("NOPASSWD", script)

    def test_text_installer_uses_an_interactive_authenticated_sudo_prompt(self):
        launcher = (AIROOTFS / "usr/bin/kinetix-install").read_text()
        self.assertIn("exec sudo archinstall", launcher)
        self.assertNotIn("sudo -n", launcher)

    def test_no_root_needing_script_relies_on_kinetix_sudo(self):
        # System services and session launchers execute with the intended
        # privilege directly, rather than bypassing authenticated sudo.
        for script in (
            "usr/bin/kinetix-session",
            "usr/bin/kinetix-shell",
            "usr/bin/kinetix-keyring-init",
        ):
            text = (AIROOTFS / script).read_text()
            self.assertNotIn("sudo ", text, msg=f"{script} shells out to sudo")


if __name__ == "__main__":
    unittest.main()
