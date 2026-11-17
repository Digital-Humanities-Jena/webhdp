"""Launch the shared WebHDP-Link example runtime."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runner import main
if __name__ == "__main__":
    main()
