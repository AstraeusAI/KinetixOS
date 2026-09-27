"""Contracts for the desktop showing the desktop folder, live."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class DesktopIconsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.icons = (ROOT / "shell/desktop/DesktopIcons.qml").read_text()
        cls.desktop = (ROOT / "shell/desktop/KinetixDesktop.qml").read_text()

    def test_desktop_folder_is_watched_live(self):
        # FolderListModel watches the directory: new folders appear at once
        self.assertIn("FolderListModel {", self.icons)
        self.assertIn("showDirsFirst: true", self.icons)
        self.assertIn("XDG_DESKTOP_DIR", self.icons)          # honours user-dirs.dirs

    def test_desktop_window_mounts_icons_and_takes_input_only_there(self):
        self.assertIn("DesktopIcons {", self.desktop)
        self.assertIn("item: icons.hitArea", self.desktop)
        self.assertIn("Region { item: icons.menuBox }", self.desktop)
        self.assertNotIn("mask: Region {}", self.desktop)      # no longer input-dead

    def test_items_open_and_trash_recoverably(self):
        self.assertIn('["gio", "open", path]', self.icons)
        self.assertIn('["gio", "trash", path]', self.icons)     # never rm

    def test_folders_use_the_kinetix_folder_icon(self):
        self.assertIn("KinetixFolder {", self.icons)
        self.assertIn("visible: cell.fileIsDir", self.icons)
        folder = (ROOT / "shell/components/KinetixFolder.qml").read_text()
        self.assertIn("property bool open", folder)
        self.assertNotIn("Animation.Infinite", folder)   # still at rest

    def test_session_creates_the_desktop_folder(self):
        session = (ROOT / "distro/archiso/airootfs/usr/bin/kinetix-shell").read_text()
        self.assertIn('mkdir -p -- "${desktop_dir:-$HOME/Desktop}"', session)


if __name__ == "__main__":
    unittest.main()
