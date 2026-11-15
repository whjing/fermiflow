"""Record the source commit when building fermiflow from a Git checkout."""

from pathlib import Path
import subprocess

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPy(build_py):
    def run(self):
        super().run()
        root = Path(__file__).resolve().parent
        commit = "unknown"
        if (root / ".git").exists():
            try:
                commit = subprocess.check_output(
                    ["git", "-C", str(root), "rev-parse", "HEAD"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
            except (OSError, subprocess.CalledProcessError):
                pass

        stamp = Path(self.build_lib) / "scripts" / "_git_commit.txt"
        stamp.write_text(commit + "\n", encoding="utf-8")


setup(cmdclass={"build_py": BuildPy})
