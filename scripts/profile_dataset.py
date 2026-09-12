#!/usr/bin/env python3
"""Profile a dataset directory and write JSON + figures to reports/.

Usage:
    python scripts/profile_dataset.py --dataset dataset_a --out reports/day1
    python scripts/profile_dataset.py --dataset dataset_b --out reports/day1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.profiling import profile_dataset
from procmine.viz import generate_all


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path, help="path to dataset_a or dataset_b")
    parser.add_argument("--out", required=True, type=Path, help="output directory for reports")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    print(f"Profiling {args.dataset} ...", file=sys.stderr)
    profile = profile_dataset(args.dataset)

    json_path = args.out / f"profile_{profile['dataset']}.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, default=str, ensure_ascii=False)
    print(f"Wrote {json_path}", file=sys.stderr)

    figures_dir = args.out / "figures"
    figure_paths = generate_all(profile, figures_dir)
    for p in figure_paths:
        print(f"Wrote {p}", file=sys.stderr)

    print(
        f"\n{profile['dataset']}: {profile['n_sessions']} sessions, "
        f"{profile['n_chunks']} chunks, {profile['n_events']} events, "
        f"{profile['sessions_with_ground_truth']} with ground truth",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
