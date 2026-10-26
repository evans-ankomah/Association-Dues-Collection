"""CSV and Excel exports. Cells that a spreadsheet could execute as a formula are neutralised."""

import csv
from decimal import Decimal
from io import BytesIO, StringIO

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _safe(value):
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


def respond(filename, headers, rows, fmt):
    rows = [[_safe(v) for v in row] for row in rows]
    if fmt == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(headers)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in rows:
            sheet.append([float(v) if isinstance(v, Decimal) else v for v in row])
        for column in sheet.columns:
            width = max(len(str(c.value or "")) for c in column)
            sheet.column_dimensions[column[0].column_letter].width = min(max(width + 2, 10), 50)
        buffer = BytesIO()
        workbook.save(buffer)
        response = HttpResponse(
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(headers)
        writer.writerows(rows)
        response = HttpResponse("\ufeff" + buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="{filename}.{"xlsx" if fmt == "xlsx" else "csv"}"'
    )
    return response
