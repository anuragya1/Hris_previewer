# HRIS Import Preview

A small standard-library Python web app for previewing an HRIS CSV before employee or reporting data is imported.

## Setup and Run

Requires Python 3.11+.

```bash
python main.py
```

Open http://127.0.0.1:8000 and upload a CSV with these headers, in any order:

```text
employee_id,employee_name,email,manager_id,manager_email,department
```

No database is used. The upload is analyzed in memory and rendered back to the browser.

## Tests

```bash
python -m unittest
```

## What the App Shows

- total source rows
- accepted employees
- row-level validation errors with source row numbers
- root employees with no manager
- managers and direct-report counts
- employees that participate in a reporting cycle

## Assumptions and Limitations

- Source row numbers treat the header as row 1, so the first data row is row 2.
- Employee IDs remain case-sensitive. Email and manager email are lowercased.
- Rows with missing or duplicated `employee_id` or `email` are rejected from manager lookup and hierarchy analysis.
- Employees with manager errors are still accepted, but they do not become roots and do not create reporting relationships.
- Uploads are limited to 5 MB in the demo server.
- The web server uses a small multipart parser scoped to the single upload field used by this app. For production, I would use Django or another maintained framework for request parsing, file limits, CSRF handling, and deployment concerns.

## Complexity

Parsing and validation are linear in the number of rows. The app builds hash maps for employee IDs, emails, and reporting edges, so manager lookup is O(1) average-case per employee. Cycle detection walks the manager pointers iteratively and visits each reporting edge once, making hierarchy analysis O(n) time and O(n) space for about 100,000 employees without relying on Python recursion depth.

## Approximate Time

About 20 minutes including implementation, tests, and README.

## AI Tools Used

I used OpenAI Codex as a coding assistant to scaffold the standard-library web app, organize the validation logic, and write focused tests. 
