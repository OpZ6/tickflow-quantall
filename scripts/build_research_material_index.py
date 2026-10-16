from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.research_materials.builder import build_research_material_index


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    print(json.dumps(build_research_material_index(args.research_dir, args.data_dir), ensure_ascii=False))
