"""Contracts for the KinetixOS window/app theme (colour scheme + decoration)."""
import configparser
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
PAYLOAD = ROOT / "distro/payload"


def ini(path):
    cp = configparser.RawConfigParser(strict=False)
    cp.optionxform = str
    cp.read(path)
    return cp


class WindowThemeTests(unittest.TestCase):
    def test_colour_scheme_is_complete_and_named(self):
        cp = ini(PAYLOAD / "usr/share/color-schemes/KinetixDark.colors")
        self.assertEqual("KinetixDark", cp.get("General", "ColorScheme"))
        for group in ("Colors:Window", "Colors:View", "Colors:Button", "Colors:Selection", "WM"):
            self.assertTrue(cp.has_section(group), group)

    def test_system_defaults_select_the_scheme_and_carry_its_colours(self):
        kg = ini(PAYLOAD / "etc/xdg/kdeglobals")
        self.assertEqual("KinetixDark", kg.get("General", "ColorScheme"))
        # apps read colours from kdeglobals itself, so the groups must be there
        self.assertTrue(kg.has_section("Colors:Window"))
        self.assertTrue(kg.has_section("WM"))
        self.assertEqual("224,26,60", kg.get("Colors:Selection", "BackgroundNormal"))

    def test_title_bars_match_the_shell_glass(self):
        kg = ini(PAYLOAD / "etc/xdg/kdeglobals")
        self.assertEqual("24,12,17", kg.get("WM", "activeBackground"))

    def test_breeze_decoration_is_configured(self):
        kw = ini(PAYLOAD / "etc/xdg/kwinrc")
        self.assertEqual("org.kde.breeze", kw.get("org.kde.kdecoration2", "library"))
        br = ini(PAYLOAD / "etc/xdg/breezerc")
        self.assertTrue(br.has_option("Common", "ShadowSize"))

    def test_ghostty_close_confirmation_is_off_by_default(self):
        text = (PAYLOAD / "etc/xdg/ghostty/config").read_text()
        self.assertIn("confirm-close-surface = false", text)

    def test_payload_reaches_both_the_iso_and_the_package(self):
        build = (ROOT / "distro/build-iso.sh").read_text()
        publish = (ROOT / "distro/publish.sh").read_text()
        self.assertIn('cp -a "$ROOT/distro/payload/." "$PROFILE/airootfs/"', build)
        self.assertIn('cp -a "$ROOT/distro/payload/." "$TREE/"', publish)


if __name__ == "__main__":
    unittest.main()
