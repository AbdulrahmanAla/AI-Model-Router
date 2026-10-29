"""Run the local merge gate without CI minutes or paid model calls."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    commands = [[sys.executable, "-m", "pytest", "-q"]]
    node = shutil.which("node")
    if node is None:
        raise SystemExit("Install Node.js for the JavaScript syntax check, then rerun.")
    for path in sorted((ROOT / "web").rglob("*.js")):
        commands.append([node, "--check", str(path)])
    commands.append([node, "--test", "tests/frontend_requests.test.cjs"])
    commands.append([sys.executable, "scripts/smoke.py"])
    for command in commands:
        print("Running", " ".join(command), flush=True)
        subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
