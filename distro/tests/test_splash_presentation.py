"""Contracts for the startup splash.

The splash is the one surface every user sees on every boot and the one with
no way to report a problem, so the decisions that are easy to undo by accident
are pinned here as text contracts — the same approach test_dock.py takes for
the dock. These assert *intent* (the exit moves the brand, not the backdrop;
ambient loops are gated; the stall is reported) rather than pixels, because
there is no display server in CI to render pixels from.

Two of these are regressions with a story:

- The exit used to fade the whole SplashContent item, which took the wallpaper
  down with it. For the length of the fade the overlay was translucent and the
  desktop's own copy of the same wallpaper showed through it — a dip in the
  middle of a handoff whose entire purpose is to be invisible.
- The stage pips read `parent.parent.modelData`, two levels up, where
  `modelData` is not actually a member of the item being read. qmllint reports
  it as a missing property; it only worked because the nesting never changed.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


def code_only(qml: str) -> str:
    """QML source with `//` line comments and doc comments removed.

    Several of these contracts are about a pattern that must be *gone*, and
    this file's own comments quote the old pattern when explaining why it was
    removed. Asserting against the raw text would then fail on the
    explanation.
    """
    out, in_block = [], False
    for line in qml.splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if in_block:
            if stripped.endswith("*/"):
                in_block = False
            continue
        # Drop a trailing // comment that is not inside a string literal.
        in_str, cut = False, None
        for i, ch in enumerate(line):
            if ch == '"':
                in_str = not in_str
            elif ch == "/" and not in_str and line[i + 1:i + 2] == "/":
                cut = i
                break
        out.append(line if cut is None else line[:cut])
    return "\n".join(out)


class MotionPreferenceTests(unittest.TestCase):
    """`Theme.reduceMotion` exists and is the single switch for the shell."""

    @classmethod
    def setUpClass(cls):
        cls.theme = (ROOT / "shell/common/Theme.qml").read_text()

    def test_the_preference_is_defined_and_reads_the_environment(self):
        self.assertIn("readonly property bool reduceMotion", self.theme)
        self.assertIn("KINETIX_REDUCE_MOTION", self.theme)

    def test_motion_is_on_by_default(self):
        # Opt-out, not opt-in. An env var nobody sets has to leave the product
        # looking the way it was designed to look.
        self.assertIn("return v === \"1\" || v === \"true\"", self.theme)
        self.assertNotIn("readonly property bool motion: false", self.theme)

    def test_ambient_and_duration_helpers_exist(self):
        # `ambient` gates loops (stop them), `ms` collapses finite transitions.
        # Two knobs because they are not the same fix: a loop shortened is
        # still a loop.
        self.assertIn("readonly property bool ambient: !reduceMotion", self.theme)
        self.assertIn("function ms(n)", self.theme)

    def test_the_preference_does_not_stop_the_heartbeat_timer(self):
        # The heartbeat is a shared clock the whole shell reads. It must keep
        # running so surfaces that have not adopted the preference yet still
        # get a live value rather than freezing at phase 0.
        self.assertNotIn("running: !reduceMotion", self.theme)


class SplashMotionGatingTests(unittest.TestCase):
    """Every motion site in the splash answers to the preference."""

    @classmethod
    def setUpClass(cls):
        cls.splash = (ROOT / "shell/desktop/SplashContent.qml").read_text()
        cls.code = code_only(cls.splash)

    def test_the_continuous_wallpaper_drift_is_ambient(self):
        # Eleven seconds of unbroken zoom with no information in it — the most
        # sustained motion in the product.
        self.assertTrue("duration: 11000" in self.code, "the 11s zoom should still exist")
        # (?s) inline: assertRegex's third positional argument is `msg`, not
        # flags, so passing re.S there silently becomes the failure message.
        self.assertRegex(
            self.code,
            r"(?s)from: 1\.075; to: 1\.0.*?running: content\.visible.*?Theme\.ambient",
            "the wallpaper Ken Burns must be gated on Theme.ambient",
        )

    def test_the_progress_shimmer_loop_stops_rather_than_slows(self):
        self.assertTrue("loops: Animation.Infinite" in self.code)
        self.assertRegex(
            self.code,
            r"(?s)loops: Animation\.Infinite.*?running: content\.visible"
            r".*?Theme\.ambient",
            "the progress shimmer must be gated on Theme.ambient",
        )

    def test_the_mark_keeps_its_entrance_when_ambient_motion_is_off(self):
        # `animated` on KinetixMark gates its internal comet/glint loops, not
        # its arrival. Gating the entrance on the same flag as the loops would
        # make the mark pop in with no animation under reduced motion, which is
        # the one thing reduced motion should not do.
        self.assertTrue("&& Theme.ambient" in self.code
                        and "animated: content.visible" in self.code)

    def test_the_active_stage_is_still_identifiable_without_the_pulse(self):
        # The pulse is decoration; "which stage am I waiting on" is not. The
        # ring stays visible at a fixed size and opacity.
        self.assertTrue("? 0.25 + 0.55 * Theme.heartbeatSin" in self.code)
        self.assertTrue(": 0.7" in self.code)

    def test_entrance_timings_go_through_the_duration_helper(self):
        # A hand-written 520 that ignores the preference is the failure mode;
        # every finite transition in the composition is wrapped.
        self.assertNotRegex(self.code, r"duration: (?:520|560|640|800|900)\b")
        self.assertGreaterEqual(self.code.count("Theme.ms("), 8)


class SplashExitTests(unittest.TestCase):
    """The departure is a hand-off, not a dissolve of everything."""

    @classmethod
    def setUpClass(cls):
        cls.splash = (ROOT / "shell/desktop/SplashContent.qml").read_text()
        cls.boot = (ROOT / "shell/desktop/BootSplash.qml").read_text()

    def test_the_backdrop_is_not_faded(self):
        # The root item holds full opacity and is never gated on `dismissed`.
        # `content.dismissed` does legitimately appear above the brand column —
        # in stalledNow, in the elapsed timer's running: — so the assertion is
        # about the opacity binding specifically, not the identifier.
        root = code_only(self.splash).split("id: stack")[0]
        self.assertTrue("opacity: 1" in root)
        self.assertTrue("opacity: content.dismissed" not in root)

    def test_exactly_one_opacity_gate_exists_and_it_is_on_the_brand_column(self):
        code = code_only(self.splash)
        self.assertEqual(
            1,
            code.count("opacity: content.dismissed ? 0 : 1"),
            "only the brand column should fade on dismissal",
        )
        self.assertLess(
            code.index("id: stack"),
            code.index("opacity: content.dismissed ? 0 : 1"),
        )

    def test_the_brand_column_owns_the_exit(self):
        self.assertIn("opacity: content.dismissed ? 0 : 1", self.splash)
        self.assertIn("y: content.dismissed ? -14 * content.unit : 0", self.splash)

    def test_the_exit_lifts_rather_than_only_fading(self):
        # A touch, on purpose: anything larger reads as the splash being
        # thrown at the desktop rather than replaced by it.
        self.assertIn("-14 * content.unit", self.splash)


class SplashHonestyTests(unittest.TestCase):
    """A splash that cannot say "this did not come up" is hiding information."""

    @classmethod
    def setUpClass(cls):
        cls.splash = (ROOT / "shell/desktop/SplashContent.qml").read_text()
        cls.boot = (ROOT / "shell/desktop/BootSplash.qml").read_text()

    def test_a_stalled_departure_names_the_subsystem(self):
        self.assertIn("stalledNow", self.splash)
        self.assertIn("not ready — continuing", self.splash)

    def test_the_stall_is_only_claimed_once_the_departure_has_begun(self):
        # Saying "not ready" during a normal boot would be crying wolf on every
        # launch; the ceiling has to be the reason.
        self.assertIn("readonly property bool stalledNow: dismissed && stalled", self.splash)

    def test_the_stall_is_latched_before_the_fade_samples_readiness(self):
        # Sampled after the fade starts, it would read the state *during* the
        # exit and could disagree with why the exit began.
        self.assertIn("splash.stalled = !splash.allDone;", self.boot)
        self.assertLess(
            self.boot.index("splash.stalled = !splash.allDone;"),
            self.boot.index("splash.fading = true;"),
        )

    def test_liveness_does_not_depend_on_motion(self):
        # The shimmer sweep was the only thing signalling "still working", and
        # it is the first thing the preference removes. The elapsed counter is
        # its replacement, and it works with animation off.
        self.assertIn("elapsed.toFixed(1)", self.splash)
        self.assertIn("readonly property bool allComplete", self.splash)


class SplashBindingTests(unittest.TestCase):
    """The pips must not read a property two levels up."""

    @classmethod
    def setUpClass(cls):
        cls.splash = (ROOT / "shell/desktop/SplashContent.qml").read_text()

    def test_no_two_level_reach_through_for_the_stage_object(self):
        self.assertTrue("parent.parent.modelData" not in code_only(self.splash),
                        "pips must not read the stage object two levels up")

    def test_delegates_hold_a_named_handle_instead(self):
        code = code_only(self.splash)
        self.assertTrue("id: stageRow" in code)
        self.assertTrue("readonly property bool done: modelData.done" in code)

    def test_nested_components_declare_bound_behaviour(self):
        # Without this, every `content.unit` reference from inside a Repeater
        # delegate is an unqualified cross-component access, which qmllint
        # flags on each one.
        self.assertIn("pragma ComponentBehavior: Bound", self.splash)


if __name__ == "__main__":
    unittest.main()
