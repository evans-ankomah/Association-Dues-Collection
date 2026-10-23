"""Rebuild seed/umat/schema.py from the DeptHub workbook's Field Dictionary sheet (requires openpyxl).

    python seed/regenerate_schema.py [path/to/DeptHub_Database_Design.xlsx]
"""
import re
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent
DEFAULT = ROOT.parent / ".product" / "DeptHub_Database_Design.xlsx"


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
    tables = {}
    for i, r in enumerate(wb["Field Dictionary"].iter_rows(values_only=True)):
        if i == 0 or not r[0]:
            continue
        table, field, pg_type, key, required, rule = r[0], r[1], r[2], r[3] or "", r[4], r[12] or ""
        col = {"type": pg_type, "required": required == "Yes"}
        fk = re.search(r"FK -> (\w+)\.id", key)
        if fk:
            col["fk"] = fk.group(1)
        if "UNIQUE" in key:
            col["unique"] = True
        enum = re.match(r"Check: ([^;]+?)(?:\.|;|$)", rule)
        if enum:
            col["enum"] = [v.strip() for v in enum.group(1).split(",")]
        tables.setdefault(table, {})[field] = col

    lines = ['"""DeptHub table definitions, generated from .product/DeptHub_Database_Design.xlsx (Field Dictionary).',
             "", "Regenerate rather than hand-edit if the workbook changes. Column order matches the workbook.",
             '"""', "", "TABLES = {"]
    for table, cols in tables.items():
        lines.append(f"    {table!r}: {{")
        lines += [f"        {f!r}: {c!r}," for f, c in cols.items()]
        lines.append("    },")
    lines.append("}")
    out = ROOT / "umat" / "schema.py"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(tables)} tables -> {out}")


if __name__ == "__main__":
    main()
