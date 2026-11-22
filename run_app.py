"""Launch the AEGIS control centre (Pygame window).

  python run_app.py            start the app
  python run_app.py --install  install the requirements first, then start

Checks that Pygame is available before starting, so a missing package gives a clear message
instead of a traceback.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIREMENTS = ROOT / "requirements.txt"
REQUIRED_MODULES = {"pygame": "pygame-ce"}     # import name -> pip package name


def missing_packages():
    return [pkg for module, pkg in REQUIRED_MODULES.items()
            if importlib.util.find_spec(module) is None]


def install():
    print(f"Installing requirements from {REQUIREMENTS.name} ...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)], check=True)


def main(argv):
    if "--install" in argv:
        install()
    missing = missing_packages()
    if missing:
        print("Missing packages:", ", ".join(missing))
        print("Run:  python run_app.py --install   (or: python -m pip install -r requirements.txt)")
        return 1
    sys.path.insert(0, str(ROOT))
    from environment.city import CityGraph
    from visualization.pygame_ui import App
    App(CityGraph.load(), use_llm=False).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
