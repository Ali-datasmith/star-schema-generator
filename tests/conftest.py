import sys
from pathlib import Path

# Ensure the project root is in sys.path for pytest execution
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
