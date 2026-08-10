import sys
from pathlib import Path

# Add the project root to Python path so imports like 'from src.rate_limit import ...' work
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
