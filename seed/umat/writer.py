"""Write generated tables as <table>.csv and <table>.json plus a manifest."""
import csv
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from .schema import TABLES


def _iso(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return value.isoformat()


def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (datetime, date)):
        return _iso(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value)


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return _iso(value)
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value))


def write_all(tables, out_dir, manifest):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "csv").mkdir(exist_ok=True)
    (out / "json").mkdir(exist_ok=True)
    counts = {}
    for table in TABLES:  # workbook order
        rows = tables.get(table)
        if rows is None:
            continue
        columns = list(TABLES[table])
        with open(out / "csv" / f"{table}.csv", "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh, lineterminator="\n")
            writer.writerow(columns)
            for row in rows:
                writer.writerow([_csv_value(row[c]) for c in columns])
        with open(out / "json" / f"{table}.json", "w", encoding="utf-8", newline="\n") as fh:
            json.dump(rows, fh, default=_json_default, ensure_ascii=False, indent=1)
            fh.write("\n")
        counts[table] = len(rows)
    manifest = {**manifest, "row_counts": counts, "total_rows": sum(counts.values())}
    with open(out / "manifest.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2, default=_json_default)
        fh.write("\n")
    return counts
