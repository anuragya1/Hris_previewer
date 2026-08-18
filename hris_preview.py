from __future__ import annotations

import csv
from dataclasses import dataclass, field
from io import StringIO
from typing import Any


REQUIRED_HEADERS = {
    "employee_id",
    "employee_name",
    "email",
    "manager_id",
    "manager_email",
    "department",
}


@dataclass(frozen=True)
class Employee:
    row_number: int
    employee_id: str
    employee_name: str
    email: str
    manager_id: str
    manager_email: str
    department: str


@dataclass
class RowIssue:
    row_number: int
    message: str


@dataclass
class PreviewResult:
    total_source_rows: int
    accepted_employees: list[Employee]
    row_errors: list[RowIssue]
    roots: list[Employee]
    managers: list[dict[str, Any]]
    cycle_employees: list[Employee]
    relationships: dict[str, str] = field(default_factory=dict)


class UploadParseError(ValueError):
    pass


def analyze_csv(upload: bytes) -> PreviewResult:
    rows = _parse_rows(upload)
    employees = [_normalize_row(row_number, raw) for row_number, raw in rows]
    errors: list[RowIssue] = []
    invalid_identity_rows: set[int] = set()

    ids: dict[str, list[Employee]] = {}
    emails: dict[str, list[Employee]] = {}
    for employee in employees:
        if not employee.employee_id:
            errors.append(RowIssue(employee.row_number, "employee_id is required."))
            invalid_identity_rows.add(employee.row_number)
        else:
            ids.setdefault(employee.employee_id, []).append(employee)

        if not employee.email:
            errors.append(RowIssue(employee.row_number, "email is required."))
            invalid_identity_rows.add(employee.row_number)
        else:
            emails.setdefault(employee.email, []).append(employee)

    for duplicate_id, duplicates in ids.items():
        if len(duplicates) > 1:
            for employee in duplicates:
                errors.append(
                    RowIssue(
                        employee.row_number,
                        f"employee_id '{duplicate_id}' is duplicated.",
                    )
                )
                invalid_identity_rows.add(employee.row_number)

    for duplicate_email, duplicates in emails.items():
        if len(duplicates) > 1:
            for employee in duplicates:
                errors.append(
                    RowIssue(
                        employee.row_number,
                        f"email '{duplicate_email}' is duplicated.",
                    )
                )
                invalid_identity_rows.add(employee.row_number)

    accepted = [
        employee
        for employee in employees
        if employee.row_number not in invalid_identity_rows
    ]
    by_id = {employee.employee_id: employee for employee in accepted}
    by_email = {employee.email: employee for employee in accepted}

    roots: list[Employee] = []
    relationships: dict[str, str] = {}
    direct_reports: dict[str, list[Employee]] = {employee.employee_id: [] for employee in accepted}

    for employee in accepted:
        manager, manager_error = _resolve_manager(employee, by_id, by_email)
        if manager_error:
            errors.append(RowIssue(employee.row_number, manager_error))
            continue

        if manager is None:
            roots.append(employee)
            continue

        relationships[employee.employee_id] = manager.employee_id
        direct_reports[manager.employee_id].append(employee)

    managers = [
        {
            "employee_id": manager.employee_id,
            "employee_name": manager.employee_name,
            "email": manager.email,
            "direct_report_count": len(reports),
        }
        for manager in accepted
        if (reports := direct_reports[manager.employee_id])
    ]
    managers.sort(key=lambda item: (-item["direct_report_count"], item["employee_name"].lower()))

    cycle_ids = _find_cycle_members(relationships)
    accepted_by_id = {employee.employee_id: employee for employee in accepted}
    cycle_employees = sorted(
        (accepted_by_id[employee_id] for employee_id in cycle_ids),
        key=lambda employee: employee.row_number,
    )

    return PreviewResult(
        total_source_rows=len(rows),
        accepted_employees=accepted,
        row_errors=sorted(errors, key=lambda error: (error.row_number, error.message)),
        roots=sorted(roots, key=lambda employee: employee.row_number),
        managers=managers,
        cycle_employees=cycle_employees,
        relationships=relationships,
    )


def _parse_rows(upload: bytes) -> list[tuple[int, dict[str, str]]]:
    try:
        text = upload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UploadParseError("Upload must be a UTF-8 CSV file.") from exc

    try:
        reader = csv.reader(StringIO(text), strict=True)
        parsed = list(reader)
    except csv.Error as exc:
        raise UploadParseError(f"Could not parse CSV: {exc}") from exc

    if not parsed:
        raise UploadParseError("CSV is empty.")

    headers = [header.strip() for header in parsed[0]]
    missing = sorted(REQUIRED_HEADERS.difference(headers))
    if missing:
        raise UploadParseError(f"CSV is missing required header(s): {', '.join(missing)}.")

    rows: list[tuple[int, dict[str, str]]] = []
    for index, values in enumerate(parsed[1:], start=2):
        if len(values) > len(headers):
            raise UploadParseError(f"Row {index} has more values than the header row.")
        padded_values = values + [""] * (len(headers) - len(values))
        rows.append((index, dict(zip(headers, padded_values))))
    return rows


def _normalize_row(row_number: int, raw: dict[str, str]) -> Employee:
    value = {header: raw.get(header, "").strip() for header in REQUIRED_HEADERS}
    value["email"] = value["email"].lower()
    value["manager_email"] = value["manager_email"].lower()
    return Employee(row_number=row_number, **value)


def _resolve_manager(
    employee: Employee,
    by_id: dict[str, Employee],
    by_email: dict[str, Employee],
) -> tuple[Employee | None, str | None]:
    has_manager_id = bool(employee.manager_id)
    has_manager_email = bool(employee.manager_email)

    if not has_manager_id and not has_manager_email:
        return None, None

    id_match = by_id.get(employee.manager_id) if has_manager_id else None
    email_match = by_email.get(employee.manager_email) if has_manager_email else None

    if has_manager_id and id_match is None:
        return None, f"manager_id '{employee.manager_id}' does not match an accepted employee."
    if has_manager_email and email_match is None:
        return None, f"manager_email '{employee.manager_email}' does not match an accepted employee."
    if id_match is not None and email_match is not None and id_match.employee_id != email_match.employee_id:
        return None, "manager_id and manager_email refer to different employees."

    manager = id_match or email_match
    if manager is not None and manager.employee_id == employee.employee_id:
        return None, "employee cannot manage themselves."

    return manager, None


def _find_cycle_members(relationships: dict[str, str]) -> set[str]:
    visited: set[str] = set()
    cycle_members: set[str] = set()

    for employee_id in relationships:
        if employee_id in visited:
            continue

        path: list[str] = []
        positions: dict[str, int] = {}
        current = employee_id

        while current in relationships and current not in visited:
            if current in positions:
                cycle_members.update(path[positions[current] :])
                break

            positions[current] = len(path)
            path.append(current)
            current = relationships[current]

        visited.update(path)

    return cycle_members
