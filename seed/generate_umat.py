"""Generate the anonymised UMaT sample dataset for DeptHub.

    python seed/generate_umat.py [--seed 2026] [--out seed/output]

Writes seed/output/csv/<table>.csv, seed/output/json/<table>.json and seed/output/manifest.json.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from umat import config  # noqa: E402
from umat.builders import audit, comms, dues, finance, ops, org, payments, people  # noqa: E402
from umat.core import Ctx  # noqa: E402
from umat.schema import TABLES  # noqa: E402
from umat.writer import write_all  # noqa: E402

PIPELINE = [org.build, people.build, org.build_role_permissions, dues.build, payments.build, finance.build,
            comms.build, ops.build, audit.build]


def generate(seed=config.SEED):
    ctx = Ctx(seed, config.AS_OF)
    for step in PIPELINE:
        step(ctx)
    return ctx


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=config.SEED)
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent / "output"))
    args = parser.parse_args()

    ctx = generate(args.seed)
    manifest = {
        "dataset": "UMaT (University of Mines and Technology, Tarkwa) - DeptHub sample data",
        "anonymised": True,
        "seed": args.seed,
        "as_of": config.AS_OF,
        "focus_department": config.FOCUS_DEPARTMENT_CODE,
        "sessions": [s["name"] for s in config.SESSIONS],
        "tables_not_generated": [t for t in TABLES if t not in ctx.tables],
    }
    counts = write_all(ctx.tables, args.out, manifest)
    width = max(map(len, counts))
    for table, n in counts.items():
        print(f"  {table:<{width}}  {n:>6}")
    print(f"{len(counts)} tables, {sum(counts.values())} rows -> {args.out}")


if __name__ == "__main__":
    main()
