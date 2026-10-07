#!/usr/bin/env python3
"""Write og-image.jpg (1200x630 social preview): the favicon, the title and a blue bar.

Draws it with og_card.py, the same card script as in sacret/genealogy and sacret/my-mind.
Needs Google Chrome and Pillow.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    subprocess.run([
        sys.executable, os.path.join(ROOT, "scripts", "og_card.py"),
        "--icon", os.path.join(ROOT, "icons", "favicon.svg"),
        "--title", "Mi activity",
        "--subtitle", "several years of Mi Band data",
        "--accent", "#2a78d6", "--bg", "#f9f9f7", "--ink", "#0b0b0b", "--muted", "#52514e",
        "--icon-size", "260", "--title-size", "120", "--sub-size", "46",
        "--out", os.path.join(ROOT, "og-image.jpg"),
    ], check=True)


if __name__ == "__main__":
    main()
