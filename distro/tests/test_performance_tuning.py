"""Round 14: I/O, memory, NVIDIA-boot-path, and gaming tuning contracts."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
DISTRO = ROOT / "distro"
PROFILE = DISTRO / "archiso"
AIROOTFS = PROFILE / "airootfs"


def _packages() -> set[str]:
    return {
        line.strip()
        for line in (PROFILE / "packages.x86_64").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


class MemoryAndIoTuningTests(unittest.TestCase):
    def test_sysctl_tunes_memory_for_zram_and_stability(self):
        text = (AIROOTFS / "etc/sysctl.d/99-kinetix-performance.conf").read_text()
        self.assertIn("vm.swappiness = 100", text)
        self.assertIn("vm.vfs_cache_pressure = 50", text)
        self.assertIn("vm.dirty_background_bytes = 67108864", text)
        self.assertIn("vm.dirty_bytes = 268435456", text)
        self.assertIn("vm.dirty_writeback_centisecs = 1500", text)
        self.assertIn("vm.page-cluster = 0", text)
        self.assertIn("vm.watermark_boost_factor = 0", text)
        self.assertIn("vm.watermark_scale_factor = 125", text)
        self.assertIn("vm.compaction_proactiveness = 50", text)
        self.assertIn("vm.max_map_count = 2147483642", text)
        self.assertIn("fs.file-max = 2097152", text)
        self.assertIn("fs.inotify.max_user_watches = 524288", text)
        self.assertIn("kernel.nmi_watchdog = 0", text)

    def test_split_lock_mitigation_tradeoff_is_disclosed(self):
        text = (AIROOTFS / "etc/sysctl.d/99-kinetix-performance.conf").read_text()
        self.assertIn("kernel.split_lock_mitigate = 0", text)
        self.assertIn("security", text.lower())
        self.assertIn("tradeoff", text.lower())

    def test_zram_generator_config_is_present_and_sane(self):
        text = (AIROOTFS / "etc/systemd/zram-generator.conf").read_text()
        self.assertIn("[zram0]", text)
        self.assertIn("zram-size = min(ram / 2, 8192)", text)
        self.assertIn("compression-algorithm = zstd", text)
        self.assertIn("fs-type = swap", text)

    def test_io_scheduler_rule_covers_nvme_ssd_and_hdd_distinctly(self):
        text = (AIROOTFS / "etc/udev/rules.d/60-kinetix-ioscheduler.rules").read_text()
        self.assertIn('KERNEL=="nvme[0-9]*n[0-9]*"', text)
        self.assertIn('ATTR{queue/scheduler}="none"', text)
        self.assertIn('ATTR{queue/rotational}=="0"', text)
        self.assertIn('ATTR{queue/scheduler}="mq-deadline"', text)
        self.assertIn('ATTR{queue/rotational}=="1"', text)
        self.assertIn('ATTR{queue/scheduler}="bfq"', text)

    def test_io_scheduler_optimizes_loop_devices_and_sata_alpm(self):
        text = (AIROOTFS / "etc/udev/rules.d/60-kinetix-ioscheduler.rules").read_text()
        self.assertIn('KERNEL=="loop[0-9]*"', text)
        self.assertIn('ATTR{queue/read_ahead_kb}="2048"', text)
        self.assertIn('KERNEL=="mmcblk[0-9]*"', text)
        self.assertIn('ATTR{link_power_management_policy}="max_performance"', text)

    def test_tuning_packages_are_declared(self):
        packages = _packages()
        self.assertTrue(
            {
                "zram-generator",
                "irqbalance",
                "ananicy-cpp",
                "cachyos-ananicy-rules",
                "power-profiles-daemon",
            }.issubset(packages)
        )

    def test_tuning_daemons_are_enabled_at_boot(self):
        builder = (DISTRO / "build-iso.sh").read_text()
        for unit in (
            "systemd-oomd.service",
            "irqbalance.service",
            "ananicy-cpp.service",
            "power-profiles-daemon.service",
        ):
            self.assertIn(
                f'"$SYSTEMD/multi-user.target.wants/{unit}"',
                builder,
                msg=f"{unit} is not enabled by build-iso.sh",
            )

    def test_fstrim_timer_is_enabled(self):
        builder = (DISTRO / "build-iso.sh").read_text()
        self.assertIn('"$SYSTEMD/timers.target.wants/fstrim.timer"', builder)

    def test_installer_profile_enables_fstrim_for_installed_storage(self):
        installer_profile = (
            AIROOTFS / "usr/share/kinetix/archinstall/kinetix_profile.py"
        ).read_text()
        self.assertIn('"fstrim.timer"', installer_profile)
        self.assertIn('"cachyos-ananicy-rules"', installer_profile)

    def test_systemd_timeouts_and_limits_are_configured(self):
        timeout_conf = (
            AIROOTFS / "etc/systemd/system.conf.d/00-timeout.conf"
        ).read_text()
        self.assertIn("DefaultTimeoutStopSec=10s", timeout_conf)
        limits_conf = (
            AIROOTFS / "etc/systemd/system.conf.d/10-limits.conf"
        ).read_text()
        self.assertIn("DefaultLimitNOFILE=2048:2097152", limits_conf)

    def test_transparent_hugepages_use_deferred_defrag(self):
        thp_conf = (AIROOTFS / "etc/tmpfiles.d/thp.conf").read_text()
        self.assertIn("transparent_hugepage/defrag", thp_conf)
        self.assertIn("defer+madvise", thp_conf)



class BootAndRuntimeIoTests(unittest.TestCase):
    def test_squashfs_uses_zstd_not_xz(self):
        text = (PROFILE / "profiledef.sh").read_text()
        self.assertIn("'-comp' 'zstd'", text)
        self.assertIn("'-Xcompression-level' '19'", text)
        # xz's BCJ filter option is meaningless (and potentially rejected)
        # under zstd — confirm the old xz-specific flags are actually gone,
        # not just no-longer-mentioned by coincidence.
        self.assertNotIn("'-comp' 'xz'", text)
        self.assertNotIn("-Xbcj", text)
        self.assertNotIn("-Xdict-size", text)

    def test_journald_is_capped_and_volatile_on_the_live_root(self):
        text = (AIROOTFS / "etc/systemd/journald.conf.d/kinetix-live.conf").read_text()
        self.assertIn("[Journal]", text)
        self.assertIn("Storage=volatile", text)
        self.assertIn("RuntimeMaxUse=64M", text)


class GamingSupportTests(unittest.TestCase):
    def test_gaming_packages_are_declared_with_multilib_counterparts(self):
        packages = _packages()
        self.assertTrue(
            {
                "gamemode",
                "lib32-gamemode",
                "mangohud",
                "lib32-mangohud",
                "gamescope",
            }.issubset(packages)
        )
        pacman_conf = (PROFILE / "pacman.conf").read_text()
        self.assertIn("[multilib]", pacman_conf)

    def test_gaming_packages_have_no_idle_daemon_to_enable(self):
        # gamemode/mangohud/gamescope activate per-invocation, not as a
        # standing service — nothing to wire into multi-user.target.wants.
        builder = (DISTRO / "build-iso.sh").read_text()
        for unit in ("gamemoded.service", "mangohud.service", "gamescope.service"):
            self.assertNotIn(unit, builder)


class NvidiaBootPathTests(unittest.TestCase):
    def test_nvidia_kernel_package_is_declared(self):
        self.assertIn("linux-cachyos-bore-nvidia-open", _packages())

    def test_nvidia_entry_exists_but_is_never_the_default(self):
        loader_conf = (PROFILE / "efiboot/loader/loader.conf").read_text()
        sys_cfg = (PROFILE / "syslinux/archiso_sys.cfg").read_text()
        nvidia_entry = (
            PROFILE / "efiboot/loader/entries/03-kinetix-nvidia.conf"
        ).read_text()
        syslinux = (PROFILE / "syslinux/archiso_sys-linux.cfg").read_text()

        self.assertIn("default 01-kinetix-bore.conf", loader_conf)
        self.assertNotIn("default 03-kinetix-nvidia.conf", loader_conf)
        self.assertIn("DEFAULT arch", sys_cfg)

        self.assertIn("vmlinuz-linux-cachyos-bore-nvidia-open", nvidia_entry)
        self.assertIn("initramfs-linux-cachyos-bore-nvidia-open.img", nvidia_entry)
        self.assertIn("LABEL arch-nvidia", syslinux)
        self.assertIn("vmlinuz-linux-cachyos-bore-nvidia-open", syslinux)

    def test_builder_installs_the_nvidia_loader_entry(self):
        builder = (DISTRO / "build-iso.sh").read_text()
        self.assertIn(
            '"$ROOT/distro/archiso/efiboot/loader/entries/03-kinetix-nvidia.conf"',
            builder,
        )
        self.assertIn(
            '"$PROFILE/efiboot/loader/entries/03-kinetix-nvidia.conf"', builder
        )


if __name__ == "__main__":
    unittest.main()
