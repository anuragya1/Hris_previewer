import unittest

from hris_preview import UploadParseError, analyze_csv


class HrisPreviewTests(unittest.TestCase):
    def test_duplicate_identity_invalidates_every_duplicate_row(self):
        result = analyze_csv(
            b"""employee_id,employee_name,email,manager_id,manager_email,department
E1,Alice,alice@example.com,,,People
E1,Alicia,alicia@example.com,,,People
E3,Bob,bob@example.com,,,Sales
E4,Robert,alice@example.com,,,Sales
"""
        )

        self.assertEqual(result.total_source_rows, 4)
        self.assertEqual([employee.employee_id for employee in result.accepted_employees], ["E3"])
        self.assertEqual(len(result.row_errors), 4)

    def test_manager_errors_do_not_make_employee_root_or_relationship(self):
        result = analyze_csv(
            b"""employee_id,employee_name,email,manager_id,manager_email,department
M1,Manager,manager@example.com,,,Operations
E1,Employee,employee@example.com,missing,,Operations
E2,Self,self@example.com,E2,,Operations
E3,Report,report@example.com,M1,manager@example.com,Operations
"""
        )

        self.assertEqual([employee.employee_id for employee in result.roots], ["M1"])
        self.assertEqual(result.relationships, {"E3": "M1"})
        self.assertEqual(
            [(error.row_number, error.message) for error in result.row_errors],
            [
                (3, "manager_id 'missing' does not match an accepted employee."),
                (4, "employee cannot manage themselves."),
            ],
        )

    def test_cycle_detection_excludes_employee_reporting_into_cycle(self):
        result = analyze_csv(
            b"""employee_id,employee_name,email,manager_id,manager_email,department
A,Ada,a@example.com,B,,Engineering
B,Bo,b@example.com,C,,Engineering
C,Cy,c@example.com,A,,Engineering
D,Dee,d@example.com,A,,Engineering
"""
        )

        self.assertEqual(
            [employee.employee_id for employee in result.cycle_employees],
            ["A", "B", "C"],
        )

    def test_malformed_csv_returns_clear_error(self):
        with self.assertRaises(UploadParseError):
            analyze_csv(b'employee_id,email\n"unterminated,email@example.com\n')


if __name__ == "__main__":
    unittest.main()
