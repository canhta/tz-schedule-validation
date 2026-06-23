"""Lightweight local upload server: pick two xlsx files in the browser, get the report.

No third-party dependencies (Python stdlib only). Run:

    python -m verifier.server            # serves on http://localhost:8000
    python -m verifier.server --port 9000

Flow: upload raw + template files -> map which sheet is which -> validate.
Sheet names are never hardcoded; the user selects them after upload.
"""
from __future__ import annotations
import argparse
import html
import secrets
import tempfile
import os
import openpyxl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .config import PAPER_MOON as SCHEMA
from . import reporter

_FORM = """<!DOCTYPE html>
<html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Schedule migration verifier</title>
<style>
body{font-family:system-ui,Arial,sans-serif;max-width:640px;margin:3rem auto;padding:0 1rem;color:#1a1a1a}
h1{font-size:1.3rem}
form{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:1.5rem;margin-top:1rem}
label{display:block;font-weight:600;margin:1rem 0 .3rem}
input[type=file],input[type=text],select{width:100%;padding:.5rem;border:1px solid #ccc;border-radius:6px}
button{margin-top:1.4rem;background:#1f2937;color:#fff;border:0;border-radius:8px;padding:.7rem 1.4rem;font-size:1rem;cursor:pointer}
.muted{color:#666;font-size:.85rem}
</style></head><body>
<h1>Schedule migration verifier</h1>
<p class='muted'>Upload an org's raw export and its converted template. Next you'll pick which
sheet is which, then the report opens in this tab.</p>
<form action='/verify' method='post' enctype='multipart/form-data'>
  <label>Organization name</label>
  <input type='text' name='org' placeholder='e.g. Paper Moon Music' value='org'>
  <label>Raw data (.xlsx)</label>
  <input type='file' name='raw' accept='.xlsx' required>
  <label>Converted template (.xlsx)</label>
  <input type='file' name='template' accept='.xlsx' required>
  <button type='submit'>Next: map sheets &rarr;</button>
</form>
</body></html>"""

# token -> {"raw": path, "tpl": path, "org": str}
_PENDING: dict[str, dict] = {}


def parse_multipart(body: bytes, boundary: bytes):
    """Minimal multipart/form-data parser. Returns {field_name: (filename|None, bytes)}."""
    delim = b"--" + boundary
    out = {}
    for part in body.split(delim):
        if not part or part in (b"--\r\n", b"--", b"\r\n"):
            continue
        head, sep, data = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        data = data[:-2] if data.endswith(b"\r\n") else data
        disp = ""
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"content-disposition"):
                disp = line.decode("latin-1")
        name = filename = None
        for token in disp.split(";"):
            token = token.strip()
            if token.startswith("name="):
                name = token[5:].strip('"')
            elif token.startswith("filename="):
                filename = token[9:].strip('"')
        if name:
            out[name] = (filename, data)
    return out


def _save_temp(data: bytes) -> str:
    f = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    f.write(data)
    f.close()
    return f.name


def list_sheets(path: str) -> list[str]:
    """Sheet names of a workbook, in document order."""
    wb = openpyxl.load_workbook(path, read_only=True)
    names = list(wb.sheetnames)
    wb.close()
    return names


def guess_sheet(names: list[str], keywords: list[str]):
    """First sheet whose name contains any keyword (case-insensitive), else None."""
    for n in names:
        low = n.lower()
        if any(k.lower() in low for k in keywords):
            return n
    return None


def _options(names, selected, include_none=False):
    opts = []
    if include_none:
        opts.append(f"<option value=''{' selected' if selected is None else ''}>(none)</option>")
    for n in names:
        sel = " selected" if n == selected else ""
        opts.append(f"<option value='{html.escape(n)}'{sel}>{html.escape(n)}</option>")
    return "".join(opts)


def _mapping_page(token, org, raw_sheets, tpl_sheets):
    raw_default = raw_sheets[0] if raw_sheets else None
    tpl_default = guess_sheet(tpl_sheets, ["template", "import", "schedule"]) or (
        tpl_sheets[0] if tpl_sheets else None)
    edge_default = guess_sheet(tpl_sheets, ["edge"])
    return f"""<!DOCTYPE html>
<html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Map sheets</title>
<style>
body{{font-family:system-ui,Arial,sans-serif;max-width:640px;margin:3rem auto;padding:0 1rem;color:#1a1a1a}}
h1{{font-size:1.3rem}}
form{{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:1.5rem;margin-top:1rem}}
label{{display:block;font-weight:600;margin:1rem 0 .3rem}}
select{{width:100%;padding:.5rem;border:1px solid #ccc;border-radius:6px}}
button{{margin-top:1.4rem;background:#1f2937;color:#fff;border:0;border-radius:8px;padding:.7rem 1.4rem;font-size:1rem;cursor:pointer}}
.muted{{color:#666;font-size:.85rem}}
</style></head><body>
<h1>Map sheets &mdash; {html.escape(org)}</h1>
<p class='muted'>Pick which sheet in each file holds the data. Defaults are guessed from the
sheet names; change any that are wrong.</p>
<form action='/verify' method='post'>
  <input type='hidden' name='token' value='{token}'>
  <label>Raw data sheet (raw file)</label>
  <select name='raw_sheet'>{_options(raw_sheets, raw_default)}</select>
  <label>Import template sheet (template file)</label>
  <select name='template_sheet'>{_options(tpl_sheets, tpl_default)}</select>
  <label>Edge-case sheet (template file)</label>
  <select name='edge_sheet'>{_options(tpl_sheets, edge_default, include_none=True)}</select>
  <button type='submit'>Validate</button>
</form>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        body = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, _FORM)
        else:
            self._send(404, "not found")

    def do_POST(self):
        if self.path != "/verify":
            self._send(404, "not found")
            return
        ctype = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        if "multipart/form-data" in ctype and "boundary=" in ctype:
            boundary = ctype.split("boundary=", 1)[1].strip().strip('"').encode("latin-1")
            fields = parse_multipart(body, boundary)
            self._step_upload(fields)
        else:
            self._step_validate(_parse_urlencoded(body))

    def _step_upload(self, fields):
        try:
            raw = fields["raw"][1]
            tpl = fields["template"][1]
        except KeyError:
            self._send(400, "both 'raw' and 'template' files are required")
            return
        org = (fields.get("org", (None, b"org"))[1] or b"org").decode("utf-8") or "org"
        token = secrets.token_urlsafe(16)
        raw_path, tpl_path = _save_temp(raw), _save_temp(tpl)
        _PENDING[token] = {"raw": raw_path, "tpl": tpl_path, "org": org}
        try:
            self._send(200, _mapping_page(token, org, list_sheets(raw_path),
                                          list_sheets(tpl_path)))
        except Exception as exc:
            self._cleanup(token)
            self._send(500, f"<pre>Could not read sheets:\n{html.escape(str(exc))}</pre>")

    def _step_validate(self, form):
        token = form.get("token")
        ctx = _PENDING.get(token)
        if not ctx:
            self._send(400, "<pre>Session expired or unknown. Please re-upload the files.</pre>")
            return
        raw_sheet = form.get("raw_sheet") or None
        template_sheet = form.get("template_sheet") or "Schedule Import Template"
        edge_sheet = form.get("edge_sheet") or None  # "" -> (none)
        try:
            rep, table = reporter.verify_org_view(
                ctx["raw"], ctx["tpl"], SCHEMA, ctx["org"],
                raw_sheet=raw_sheet, template_sheet=template_sheet, edge_sheet=edge_sheet)
            self._send(200, reporter.report_to_html(rep, table))
        except Exception as exc:  # surface parsing/schema errors to the user
            self._send(500, f"<pre>Verification failed:\n{html.escape(str(exc))}</pre>")
        finally:
            self._cleanup(token)

    def _cleanup(self, token):
        ctx = _PENDING.pop(token, None)
        if not ctx:
            return
        for key in ("raw", "tpl"):
            try:
                os.unlink(ctx[key])
            except OSError:
                pass

    def log_message(self, *args):
        pass


def _parse_urlencoded(body: bytes) -> dict:
    from urllib.parse import parse_qs
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items()}


def run(port=8000, host="127.0.0.1"):
    srv = ThreadingHTTPServer((host, port), _Handler)
    print(f"Upload verifier running at http://{host}:{port}  (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Local upload server for the migration verifier.")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address (use 0.0.0.0 in a container)")
    args = ap.parse_args(argv)
    run(args.port, args.host)


if __name__ == "__main__":
    main()
