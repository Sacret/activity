#!/usr/bin/env python3
"""Write og-image.png (1200x630 social preview): a light-mode snapshot of the top of index.html.

Needs Google Chrome; run after build_page.py.
"""
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def main():
    out = os.path.join(ROOT, "og-image.png")
    subprocess.run([
        CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--blink-settings=preferredColorScheme=1",  # light
        "--window-size=1200,630", "--virtual-time-budget=3000",
        f"--screenshot={out}", "file://" + os.path.join(ROOT, "index.html"),
    ], check=True, stderr=subprocess.DEVNULL)
    print("og-image.png written")


if __name__ == "__main__":
    main()
