from __future__ import annotations

import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from hris_preview import PreviewResult, UploadParseError, analyze_csv


HOST = "127.0.0.1"
PORT = 8000
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
BASE_DIR = Path(__file__).resolve().parent


class HrisPreviewHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in {"/", "/index.html"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._send_html(render_page())

    def do_POST(self) -> None:
        if self.path != "/preview":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            upload = self._read_upload()
            result = analyze_csv(upload)
            self._send_html(render_page(result=result))
        except (UploadParseError, ValueError) as exc:
            self._send_html(render_page(upload_error=str(exc)), HTTPStatus.BAD_REQUEST)

    def _read_upload(self) -> bytes:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            raise ValueError("Choose a CSV file to upload.")
        if content_length > MAX_UPLOAD_BYTES:
            raise ValueError("Upload is too large. The demo limit is 5 MB.")

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ValueError("Upload form must use multipart/form-data.")

        boundary = _extract_boundary(content_type)
        body = self.rfile.read(content_length)
        return _extract_file_part(body, boundary)

    def _send_html(self, page: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = page.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _extract_boundary(content_type: str) -> bytes:
    parts = [part.strip() for part in content_type.split(";")]
    for part in parts:
        if part.startswith("boundary="):
            boundary = part.removeprefix("boundary=").strip('"')
            return ("--" + boundary).encode("utf-8")
    raise ValueError("Malformed upload: missing multipart boundary.")


def _extract_file_part(body: bytes, boundary: bytes) -> bytes:
    for part in body.split(boundary):
        if b'name="csv_file"' not in part:
            continue
        header_end = part.find(b"\r\n\r\n")
        separator_length = 4
        if header_end == -1:
            header_end = part.find(b"\n\n")
            separator_length = 2
        if header_end == -1:
            raise ValueError("Malformed upload: file part is missing headers.")

        content = part[header_end + separator_length :]
        if content.endswith(b"\r\n"):
            content = content[:-2]
        elif content.endswith(b"\n"):
            content = content[:-1]
        return content
    raise ValueError("Choose a CSV file to upload.")


def render_page(result: PreviewResult | None = None, upload_error: str | None = None) -> str:
    template = (BASE_DIR / "index.html").read_text(encoding="utf-8")
    return template.replace("{{RESULT}}", render_result(result, upload_error))


def render_result(result: PreviewResult | None, upload_error: str | None) -> str:
    if upload_error:
        return f'<section class="alert"><h2>Upload problem</h2><p>{escape(upload_error)}</p></section>'
    if result is None:
        return ""

    summary = f"""
    <section class="summary-grid">
      {metric("Source rows", result.total_source_rows)}
      {metric("Accepted employees", len(result.accepted_employees))}
      {metric("Validation errors", len(result.row_errors))}
      {metric("Roots", len(result.roots))}
      {metric("Managers", len(result.managers))}
      {metric("Cycle members", len(result.cycle_employees))}
    </section>
    """

    return summary + "\n".join(
        [
            employee_table("Root employees", result.roots),
            manager_table(result.managers),
            employee_table("Employees in reporting cycles", result.cycle_employees),
            error_table(result.row_errors),
        ]
    )


def metric(label: str, value: int) -> str:
    return f'<article class="metric"><span>{escape(label)}</span><strong>{value}</strong></article>'


def employee_table(title: str, employees: list[Any]) -> str:
    rows = "".join(
        f"""
        <tr>
          <td>{employee.row_number}</td>
          <td>{escape(employee.employee_id)}</td>
          <td>{escape(employee.employee_name)}</td>
          <td>{escape(employee.email)}</td>
          <td>{escape(employee.department)}</td>
        </tr>
        """
        for employee in employees
    )
    return f"""
    <section>
      <h2>{escape(title)}</h2>
      <table>
        <thead><tr><th>Row</th><th>ID</th><th>Name</th><th>Email</th><th>Department</th></tr></thead>
        <tbody>{rows or empty_row(5)}</tbody>
      </table>
    </section>
    """


def manager_table(managers: list[dict[str, Any]]) -> str:
    rows = "".join(
        f"""
        <tr>
          <td>{escape(manager["employee_id"])}</td>
          <td>{escape(manager["employee_name"])}</td>
          <td>{escape(manager["email"])}</td>
          <td>{manager["direct_report_count"]}</td>
        </tr>
        """
        for manager in managers
    )
    return f"""
    <section>
      <h2>Managers by direct reports</h2>
      <table>
        <thead><tr><th>ID</th><th>Name</th><th>Email</th><th>Direct reports</th></tr></thead>
        <tbody>{rows or empty_row(4)}</tbody>
      </table>
    </section>
    """


def error_table(errors: list[Any]) -> str:
    rows = "".join(
        f"<tr><td>{error.row_number}</td><td>{escape(error.message)}</td></tr>"
        for error in errors
    )
    return f"""
    <section>
      <h2>Row-level validation errors</h2>
      <table>
        <thead><tr><th>Source row</th><th>Error</th></tr></thead>
        <tbody>{rows or empty_row(2)}</tbody>
      </table>
    </section>
    """


def empty_row(colspan: int) -> str:
    return f'<tr><td colspan="{colspan}" class="empty">None found</td></tr>'


def escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), HrisPreviewHandler)
    print(f"HRIS import preview running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
