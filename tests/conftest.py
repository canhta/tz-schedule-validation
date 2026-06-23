import datetime as dt
import openpyxl
import pytest

@pytest.fixture
def make_xlsx(tmp_path):
    def _make(sheets: dict):  # {sheet_name: (headers, rows)}
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        for name, (headers, rows) in sheets.items():
            ws = wb.create_sheet(title=name)
            ws.append(headers)
            for r in rows:
                ws.append(list(r))
        p = tmp_path / "book.xlsx"
        wb.save(p)
        return str(p)
    return _make
