"""Desktop-icon entry point. Run with pythonw.exe so no console window appears.

Starts the Streamlit server in the background if it isn't already running, waits
for it to come up, then opens the app in your default browser. Clicking the icon
again just re-opens the browser tab.
"""
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = 8517
URL = f"http://localhost:{PORT}"
LOG = ROOT / "data" / "app.log"


def is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/_stcore/health", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def alert(msg: str) -> None:
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, msg, "HFC Model Refresh", 0x10)
    else:
        print(msg, file=sys.stderr)


def main() -> None:
    if not is_up():
        LOG.parent.mkdir(parents=True, exist_ok=True)
        python = Path(sys.executable)
        if python.name.lower() == "pythonw.exe":  # child needs a real interpreter; it's still hidden below
            python = python.with_name("python.exe")
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        with open(LOG, "a", encoding="utf-8") as log:
            subprocess.Popen(
                [str(python), "-m", "streamlit", "run", str(ROOT / "app" / "Home.py"),
                 "--server.port", str(PORT), "--server.headless", "true"],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
            )
        for _ in range(60):
            if is_up():
                break
            time.sleep(0.5)
        else:
            alert(f"The app didn't start within 30 seconds.\n\nDetails are in:\n{LOG}")
            return
    webbrowser.open(URL)


if __name__ == "__main__":
    main()
