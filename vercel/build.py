"""Build the unchanged Stage 4 frontend for the Vercel deployment."""
import os
from pathlib import Path
import subprocess

web = Path(__file__).resolve().parents[1] / "stage-4" / "web"
npm = "npm.cmd" if os.name == "nt" else "npm"
subprocess.run([npm, "ci"], cwd=web, check=True)
subprocess.run([npm, "run", "build"], cwd=web, check=True)
