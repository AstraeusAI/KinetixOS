import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MERGER = ROOT / "distro/scripts/merge-packages.py"


class MergePackagesTests(unittest.TestCase):
    def test_additions_are_appended_once_while_comments_and_blank_lines_are_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            base = temp / "base.txt"
            additions = temp / "additions.txt"
            output = temp / "merged.txt"
            base.write_text("# upstream\nlinux\nshared\n\n")
            additions.write_text("quickshell\nshared\n# local comment\nghostty\n")

            subprocess.run(
                [sys.executable, str(MERGER), str(base), str(additions), str(output)],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                ["linux", "shared", "quickshell", "ghostty"],
                output.read_text().splitlines(),
            )


if __name__ == "__main__":
    unittest.main()
