"""The KinetixOS update system: package repo, kinetix command, migrations.

These tests execute the shipped scripts where they can be executed safely in a
throwaway tree — the migration runner and the update checker are real logic,
not just file contents, so they are run rather than grepped. The parts that
need root or a live pacman (adopting the package, applying a firewall) are
asserted structurally, with the reason stated, rather than faked into passing.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DISTRO = ROOT / "distro"
PAYLOAD_BIN = DISTRO / "payload/usr/bin"
AIROOTFS = DISTRO / "archiso/airootfs"


def run(args, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    return subprocess.run(args, check=False, **kw)


class VersionAndRepoConfigTests(unittest.TestCase):
    def test_version_is_a_valid_pkgver(self):
        v = (DISTRO / "version").read_text().strip()
        self.assertRegex(v, r"^[0-9][0-9A-Za-z._+]*$", "distro/version must be a valid pkgver")

    def test_both_pkgbuilds_carry_the_same_version_as_distro_version(self):
        # publish.sh rewrites pkgver from distro/version at build time, but the
        # checked-in value should not be stale, or a `makepkg` run by hand
        # would build a differently-versioned package than publish.sh.
        v = (DISTRO / "version").read_text().strip()
        for name in ("kinetix", "kinetix-keyring"):
            text = (DISTRO / "package" / name / "PKGBUILD").read_text()
            with self.subTest(pkg=name):
                self.assertIn(f"pkgver={v}", text)

    def test_mirrorlist_url_matches_repo_conf(self):
        conf = {}
        for line in (DISTRO / "repo.conf").read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, val = line.partition("=")
                conf[k.strip()] = val.strip().strip('"')
        owner = conf["KINETIX_REPO_OWNER"].lower()
        name = conf["KINETIX_REPO_NAME"]
        mirror = (DISTRO / "repo/kinetix-mirrorlist").read_text()
        self.assertIn(f"https://{owner}.github.io/{name}/$arch", mirror)

    def test_iso_pacman_conf_stanza_matches_the_canonical_one(self):
        # Two copies exist on purpose — the static ISO pacman.conf and the
        # stanza publish/setup reference — and drift between them would mean a
        # live session with a repo the target does not have (or vice versa).
        canonical = (DISTRO / "repo/kinetix.conf").read_text()
        stanza = (
            "[kinetix]\nSigLevel = Never\n"
            "Include = /etc/pacman.d/kinetix-mirrorlist\n"
        )
        self.assertIn(stanza, canonical)
        self.assertIn(stanza, (DISTRO / "archiso/pacman.conf").read_text())

    def test_kinetix_repo_is_unsigned_by_choice_with_a_way_back(self):
        # Chosen 2026-09-27: CI publishes unsigned packages from `stable`, so
        # the repo accepts them. The prose must say how to turn signing back
        # on, and the signing path must still exist in publish.sh.
        canonical = (DISTRO / "repo/kinetix.conf").read_text()
        directives = [ln.strip() for ln in canonical.splitlines()
                      if ln.strip().startswith("SigLevel")]
        self.assertEqual(["SigLevel = Never"], directives)
        self.assertIn("Required DatabaseOptional", canonical)   # the way back
        installer = (DISTRO / "archiso/airootfs/usr/share/kinetix/archinstall/kinetix_profile.py").read_text()
        self.assertIn("SigLevel = Never", installer)
        self.assertNotIn("SigLevel = Required", installer)


class MigrationRunnerTests(unittest.TestCase):
    """kinetix-migrations is run for real against a throwaway tree."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kinetix-migr-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.migrations = self.tmp / "migrations"
        self.state = self.tmp / "state"
        self.migrations.mkdir()
        self.script = PAYLOAD_BIN / "kinetix-migrations"

    def _env(self):
        env = dict(os.environ)
        env["KINETIX_MIGRATIONS_DIR"] = str(self.migrations)
        env["KINETIX_STATE_DIR"] = str(self.state)
        return env

    def _write(self, name, body):
        p = self.migrations / name
        p.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body)
        p.chmod(0o755)
        return p

    def test_runs_pending_migrations_in_order_and_marks_them(self):
        log = self.tmp / "order.txt"
        self._write("0002-second.sh", f'echo two >> "{log}"\n')
        self._write("0001-first.sh", f'echo one >> "{log}"\n')
        r = run(["bash", str(self.script), "run"], env=self._env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(log.read_text().splitlines(), ["one", "two"])
        applied = sorted(p.name for p in (self.state / "migrations-applied").iterdir())
        self.assertEqual(applied, ["0001-first.sh", "0002-second.sh"])

    def test_a_second_run_applies_nothing(self):
        log = self.tmp / "runs.txt"
        self._write("0001-once.sh", f'echo x >> "{log}"\n')
        run(["bash", str(self.script), "run"], env=self._env())
        r = run(["bash", str(self.script), "run"], env=self._env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("nothing to apply", r.stdout)
        self.assertEqual(len(log.read_text().splitlines()), 1)

    def test_a_failing_migration_stops_and_is_not_marked(self):
        self._write("0001-ok.sh", "true\n")
        self._write("0002-boom.sh", "exit 3\n")
        self._write("0003-never.sh", f'echo never >> "{self.tmp}/never.txt"\n')
        r = run(["bash", str(self.script), "run"], env=self._env())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("0002-boom.sh failed", r.stderr)
        # 0003 must not have run, and 0002 must not be marked, so a fixed
        # version is retried on the next update rather than skipped.
        self.assertFalse((self.tmp / "never.txt").exists())
        applied = [p.name for p in (self.state / "migrations-applied").iterdir()]
        self.assertEqual(applied, ["0001-ok.sh"])

    def test_status_reports_pending_via_exit_code(self):
        self._write("0001-pending.sh", "true\n")
        r = run(["bash", str(self.script), "status"], env=self._env())
        self.assertEqual(r.returncode, 10)

    def test_list_shows_pending_then_applied(self):
        self._write("0001-a.sh", "true\n")
        before = run(["bash", str(self.script), "list"], env=self._env()).stdout
        self.assertIn("pending", before)
        run(["bash", str(self.script), "run"], env=self._env())
        after = run(["bash", str(self.script), "list"], env=self._env()).stdout
        self.assertIn("applied", after)

    def test_an_empty_directory_is_not_an_error(self):
        r = run(["bash", str(self.script), "run"], env=self._env())
        self.assertEqual(r.returncode, 0, r.stderr)


class UpdateCheckTests(unittest.TestCase):
    """kinetix-check is run with a fake checkupdates on PATH."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kinetix-check-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.script = PAYLOAD_BIN / "kinetix-check"

    def _fake_checkupdates(self, lines):
        p = self.bin / "checkupdates"
        p.write_text("#!/usr/bin/env bash\n" + "".join(f'echo "{l}"\n' for l in lines))
        p.chmod(0o755)

    def _env(self):
        env = dict(os.environ)
        env["PATH"] = str(self.bin) + os.pathsep + env["PATH"]
        return env

    def test_returns_10_and_counts_when_updates_exist(self):
        self._fake_checkupdates(["linux 6.0 -> 6.1", "kinetix 0.1.0 -> 0.2.0"])
        r = run(["bash", str(self.script), "--json"], env=self._env())
        self.assertEqual(r.returncode, 10)
        data = json.loads(r.stdout)
        self.assertEqual(data["count"], 2)
        self.assertTrue(data["kinetix"])

    def test_returns_0_and_zero_when_up_to_date(self):
        self._fake_checkupdates([])
        r = run(["bash", str(self.script), "--json"], env=self._env())
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout)["count"], 0)

    def test_blank_lines_are_not_counted_as_packages(self):
        # checkupdates can emit a trailing newline; counting it would show a
        # permanent phantom "1 update available".
        self._fake_checkupdates(["", "vim 9.0 -> 9.1", ""])
        r = run(["bash", str(self.script), "--json"], env=self._env())
        self.assertEqual(json.loads(r.stdout)["count"], 1)

    def test_write_cache_is_valid_json_for_the_shell(self):
        self._fake_checkupdates(["vim 9.0 -> 9.1"])
        cache = self.tmp / "updates.json"
        run(["bash", str(self.script), "--write-cache", str(cache)], env=self._env())
        self.assertEqual(json.loads(cache.read_text())["count"], 1)


class UpdateOrderTests(unittest.TestCase):
    """kinetix update's step order is the contract; --dry-run pins it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kinetix-upd-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.script = PAYLOAD_BIN / "kinetix-update"

    def _env(self):
        env = dict(os.environ)
        env["KINETIX_STATE_DIR"] = str(self.tmp / "state")
        # A pacman that reports no kernels and does nothing, so the dry run
        # can be asserted without root.
        fake = self.tmp / "pacman"
        fake.write_text("#!/usr/bin/env bash\nexit 0\n")
        fake.chmod(0o755)
        env["KINETIX_PACMAN"] = str(fake)
        return env

    def test_dry_run_orders_snapshot_before_pacman_before_migrations(self):
        r = run(["bash", str(self.script), "--dry-run"], env=self._env())
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        i_snap = out.find("kinetix-snapshot")
        i_pacman = out.find("pacman -Syu")
        i_migr = out.find("kinetix-migrations run")
        self.assertGreaterEqual(i_snap, 0, out)
        self.assertGreaterEqual(i_pacman, 0, out)
        self.assertGreaterEqual(i_migr, 0, out)
        self.assertLess(i_snap, i_pacman, "snapshot must precede the package transaction")
        self.assertLess(i_pacman, i_migr, "migrations run after packages are replaced")

    def test_dry_run_changes_nothing(self):
        r = run(["bash", str(self.script), "--dry-run"], env=self._env())
        self.assertIn("[dry-run]", r.stdout)
        self.assertFalse((self.tmp / "state").exists(), "dry run created state")

    def test_no_snapshot_is_honoured_and_stated(self):
        r = run(["bash", str(self.script), "--dry-run", "--no-snapshot"], env=self._env())
        self.assertIn("snapshot skipped", r.stdout)
        self.assertNotIn("kinetix-snapshot", r.stdout)

    def test_it_writes_a_lock_and_re_execs_with_original_arguments(self):
        # The sudo re-exec must carry the real flags; the parse loop shifts
        # them away, so the script keeps an ORIG_ARGS copy. A regression here
        # silently drops --no-snapshot / --yes.
        text = self.script.read_text()
        self.assertIn("ORIG_ARGS=(\"$@\")", text)
        self.assertIn('exec sudo -- "$0" "${ORIG_ARGS[@]}"', text)
        self.assertIn("flock -n 9", text)

    def test_current_install_is_adopted_into_the_package(self):
        # pacman -Syu never installs a package that was not installed, so the
        # loose install would never come under package management without an
        # explicit adopt step.
        text = self.script.read_text()
        self.assertIn("adopt_kinetix", text)
        self.assertIn("--overwrite", text)
        self.assertIn("kinetix kinetix-keyring", text)


class SudoPasswordlessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kinetix-sudo-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.script = PAYLOAD_BIN / "kinetix-sudo-passwordless"
        self.sudoers = self.tmp / "sudoers.d"
        self.state = self.tmp / "state"
        self.sudoers.mkdir()

    def _env(self):
        env = dict(os.environ)
        env["KINETIX_SUDOERS_DIR"] = str(self.sudoers)
        env["KINETIX_STATE_DIR"] = str(self.state)
        return env

    def test_off_removes_the_drop_in_without_needing_root(self):
        dropin = self.sudoers / "99-kinetix-passwordless"
        dropin.write_text("x")
        r = run(["bash", str(self.script), "off"], env=self._env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(dropin.exists())

    def test_minutes_are_validated_before_any_privilege_is_requested(self):
        # These must fail fast, before the sudo re-exec, so a typo never turns
        # into an interactive password prompt.
        for bad in ("0", "abc", "-5", "99999"):
            with self.subTest(minutes=bad):
                r = run(["bash", str(self.script), bad], env=self._env())
                self.assertNotEqual(r.returncode, 0, r.stderr)
                # It failed on the argument, and never got as far as granting
                # the window (which would have printed "granted").
                self.assertIn("MINUTES", r.stderr)
                self.assertNotIn("granted", r.stdout + r.stderr)

    def test_the_grant_is_temporary_and_documented_as_such(self):
        text = self.script.read_text()
        self.assertIn("NOPASSWD: ALL", text)
        self.assertIn("systemd-run", text)          # auto-revoke armed
        self.assertIn("on-active", text)
        # The boot cleanup unit is the other half of the expiry promise.
        unit = (
            DISTRO / "payload/usr/lib/systemd/system"
            "/kinetix-sudo-passwordless-cleanup.service"
        )
        self.assertTrue(unit.is_file())
        self.assertIn("kinetix-sudo-passwordless off", unit.read_text())


class PackagingTests(unittest.TestCase):
    def test_both_packages_have_a_pkgbuild_and_install_script(self):
        for name in ("kinetix", "kinetix-keyring"):
            with self.subTest(pkg=name):
                self.assertTrue((DISTRO / "package" / name / "PKGBUILD").is_file())
                self.assertTrue((DISTRO / "package" / name / f"{name}.install").is_file())

    def test_the_kinetix_package_owns_what_the_installer_copies(self):
        # The whole reason to package: the files archinstall copies loose must
        # be the files the package owns, or the first upgrade can overwrite
        # something it does not track (or leave a stale copy behind).
        text = (DISTRO / "package/kinetix/PKGBUILD").read_text()
        self.assertIn("tree", text)
        # publish.sh stages the payload from the same sources.
        pub = (DISTRO / "publish.sh").read_text()
        for src in ("distro/payload", "shell", "runtime", "scripts", "distro/version"):
            with self.subTest(src=src):
                self.assertIn(src, pub)

    def test_publish_signs_by_default_and_can_publish_unsigned(self):
        pub = (DISTRO / "publish.sh").read_text()
        self.assertIn("setup-signing.sh", pub)
        self.assertIn("--sign", pub)
        self.assertIn("--detach-sign", pub)
        self.assertIn("--unsigned) UNSIGNED=1", pub)
        self.assertIn("signargs=(--nosign)", pub)

    def test_setup_signing_writes_all_three_keyring_files(self):
        text = (DISTRO / "setup-signing.sh").read_text()
        for f in ("kinetix.gpg", "kinetix-trusted", "kinetix-revoked"):
            with self.subTest(file=f):
                self.assertIn(f, text)


class IsoAndInstallerWiringTests(unittest.TestCase):
    def test_iso_pacman_conf_has_the_kinetix_repo(self):
        text = (DISTRO / "archiso/pacman.conf").read_text()
        self.assertIn("[kinetix]", text)
        self.assertIn("kinetix-mirrorlist", text)

    def test_iso_ships_the_update_tooling_and_repo_config(self):
        builder = (DISTRO / "build-iso.sh").read_text()
        self.assertIn("distro/payload", builder)
        self.assertIn("distro/version", builder)
        self.assertIn("distro/repo/kinetix-mirrorlist", builder)
        self.assertIn("kinetix-keyring", builder)

    def test_keyring_init_populates_the_kinetix_key(self):
        text = (AIROOTFS / "usr/bin/kinetix-keyring-init").read_text()
        self.assertIn("pacman-key --populate kinetix", text)

    def test_installer_writes_the_repo_and_populates_the_key(self):
        text = (
            AIROOTFS / "usr/share/kinetix/archinstall/kinetix_profile.py"
        ).read_text()
        self.assertIn("kinetix-mirrorlist", text)
        self.assertIn("[kinetix]", text)
        self.assertIn("pacman-key --populate kinetix", text)

    def test_installer_enables_the_default_deny_firewall(self):
        text = (
            AIROOTFS / "usr/share/kinetix/archinstall/kinetix_profile.py"
        ).read_text()
        self.assertIn("ufw default deny incoming", text)
        self.assertIn("ufw --force enable", text)

    def test_iso_ships_ufw_and_pacman_contrib(self):
        packages = (DISTRO / "archiso/packages.x86_64").read_text()
        for pkg in ("ufw", "pacman-contrib"):
            with self.subTest(pkg=pkg):
                self.assertRegex(packages, rf"(?m)^{pkg}$")


class ShellIntegrationTests(unittest.TestCase):
    def test_update_capsule_exists_and_is_in_the_bar(self):
        self.assertTrue((ROOT / "shell/bar/UpdateCapsule.qml").is_file())
        bar = (ROOT / "shell/bar/Bar.qml").read_text()
        self.assertIn("UpdateCapsule {", bar)

    def test_the_capsule_runs_the_real_check_command_and_update_command(self):
        text = (ROOT / "shell/bar/UpdateCapsule.qml").read_text()
        self.assertIn('"kinetix", "check", "--json"', text)
        self.assertIn('"kinetix", "update"', text)

    def test_crash_notification_offers_diagnose(self):
        text = (ROOT / "shell/common/Notif.qml").read_text()
        self.assertIn('"@diagnose"', text)
        self.assertIn("function diagnoseCrash", text)
        self.assertIn("ArgusBridge.send", text)


if __name__ == "__main__":
    unittest.main()
