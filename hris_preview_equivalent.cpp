#include <algorithm>
#include <cctype>
#include <iostream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

using namespace std;

const unordered_set<string> REQUIRED_HEADERS = {
    "employee_id",
    "employee_name",
    "email",
    "manager_id",
    "manager_email",
    "department",
};

struct Employee {
    int row_number;
    string employee_id;
    string employee_name;
    string email;
    string manager_id;
    string manager_email;
    string department;
};

struct RowIssue {
    int row_number;
    string message;
};

struct ManagerSummary {
    string employee_id;
    string employee_name;
    string email;
    int direct_report_count;
};

struct PreviewResult {
    int total_source_rows;
    vector<Employee> accepted_employees;
    vector<RowIssue> row_errors;
    vector<Employee> roots;
    vector<ManagerSummary> managers;
    vector<Employee> cycle_employees;
    unordered_map<string, string> relationships;
};

class UploadParseError : public runtime_error {
public:
    explicit UploadParseError(const string& message) : runtime_error(message) {}
};

string trim(const string& value) {
    size_t start = 0;
    while (start < value.size() && isspace(static_cast<unsigned char>(value[start]))) {
        start++;
    }

    size_t end = value.size();
    while (end > start && isspace(static_cast<unsigned char>(value[end - 1]))) {
        end--;
    }

    return value.substr(start, end - start);
}

string lowercase(string value) {
    transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(tolower(ch));
    });
    return value;
}

vector<vector<string>> parse_csv_records(const string& upload) {
    string text = upload;
    if (text.size() >= 3 &&
        static_cast<unsigned char>(text[0]) == 0xEF &&
        static_cast<unsigned char>(text[1]) == 0xBB &&
        static_cast<unsigned char>(text[2]) == 0xBF) {
        text.erase(0, 3);
    }

    vector<vector<string>> records;
    vector<string> row;
    string field;
    bool in_quotes = false;

    for (size_t index = 0; index < text.size(); index++) {
        char ch = text[index];

        if (in_quotes) {
            if (ch == '"') {
                if (index + 1 < text.size() && text[index + 1] == '"') {
                    field.push_back('"');
                    index++;
                } else {
                    in_quotes = false;
                }
            } else {
                field.push_back(ch);
            }
            continue;
        }

        if (ch == '"') {
            if (!field.empty()) {
                throw UploadParseError("Could not parse CSV: unexpected quote in unquoted field.");
            }
            in_quotes = true;
        } else if (ch == ',') {
            row.push_back(field);
            field.clear();
        } else if (ch == '\n') {
            row.push_back(field);
            field.clear();
            if (!row.empty() && !row.back().empty() && row.back().back() == '\r') {
                row.back().pop_back();
            }
            records.push_back(row);
            row.clear();
        } else {
            field.push_back(ch);
        }
    }

    if (in_quotes) {
        throw UploadParseError("Could not parse CSV: unterminated quoted field.");
    }

    if (!field.empty() || !row.empty()) {
        row.push_back(field);
        if (!row.empty() && !row.back().empty() && row.back().back() == '\r') {
            row.back().pop_back();
        }
        records.push_back(row);
    }

    return records;
}

vector<pair<int, unordered_map<string, string>>> parse_rows(const string& upload) {
    vector<vector<string>> parsed = parse_csv_records(upload);
    if (parsed.empty()) {
        throw UploadParseError("CSV is empty.");
    }

    vector<string> headers;
    unordered_set<string> seen_headers;
    for (const string& header : parsed[0]) {
        string normalized_header = trim(header);
        headers.push_back(normalized_header);
        seen_headers.insert(normalized_header);
    }

    vector<string> missing;
    for (const string& required : REQUIRED_HEADERS) {
        if (seen_headers.find(required) == seen_headers.end()) {
            missing.push_back(required);
        }
    }
    sort(missing.begin(), missing.end());
    if (!missing.empty()) {
        string message = "CSV is missing required header(s): ";
        for (size_t index = 0; index < missing.size(); index++) {
            if (index > 0) {
                message += ", ";
            }
            message += missing[index];
        }
        message += ".";
        throw UploadParseError(message);
    }

    vector<pair<int, unordered_map<string, string>>> rows;
    for (size_t row_index = 1; row_index < parsed.size(); row_index++) {
        vector<string> values = parsed[row_index];
        int source_row_number = static_cast<int>(row_index) + 1;

        if (values.size() > headers.size()) {
            throw UploadParseError("Row " + to_string(source_row_number) +
                                   " has more values than the header row.");
        }

        unordered_map<string, string> row;
        for (size_t column = 0; column < headers.size(); column++) {
            row[headers[column]] = column < values.size() ? values[column] : "";
        }
        rows.push_back({source_row_number, row});
    }

    return rows;
}

Employee normalize_row(int row_number, const unordered_map<string, string>& raw) {
    auto get_value = [&](const string& header) {
        auto it = raw.find(header);
        if (it == raw.end()) {
            return string("");
        }
        return trim(it->second);
    };

    Employee employee{
        row_number,
        get_value("employee_id"),
        get_value("employee_name"),
        lowercase(get_value("email")),
        get_value("manager_id"),
        lowercase(get_value("manager_email")),
        get_value("department"),
    };
    return employee;
}

pair<const Employee*, string> resolve_manager(
    const Employee& employee,
    const unordered_map<string, const Employee*>& by_id,
    const unordered_map<string, const Employee*>& by_email
) {
    bool has_manager_id = !employee.manager_id.empty();
    bool has_manager_email = !employee.manager_email.empty();

    if (!has_manager_id && !has_manager_email) {
        return {nullptr, ""};
    }

    const Employee* id_match = nullptr;
    const Employee* email_match = nullptr;

    if (has_manager_id) {
        auto it = by_id.find(employee.manager_id);
        if (it != by_id.end()) {
            id_match = it->second;
        }
    }

    if (has_manager_email) {
        auto it = by_email.find(employee.manager_email);
        if (it != by_email.end()) {
            email_match = it->second;
        }
    }

    if (has_manager_id && id_match == nullptr) {
        return {nullptr, "manager_id '" + employee.manager_id +
                             "' does not match an accepted employee."};
    }

    if (has_manager_email && email_match == nullptr) {
        return {nullptr, "manager_email '" + employee.manager_email +
                             "' does not match an accepted employee."};
    }

    if (id_match != nullptr && email_match != nullptr &&
        id_match->employee_id != email_match->employee_id) {
        return {nullptr, "manager_id and manager_email refer to different employees."};
    }

    const Employee* manager = id_match != nullptr ? id_match : email_match;
    if (manager != nullptr && manager->employee_id == employee.employee_id) {
        return {nullptr, "employee cannot manage themselves."};
    }

    return {manager, ""};
}

unordered_set<string> find_cycle_members(const unordered_map<string, string>& relationships) {
    unordered_set<string> visited;
    unordered_set<string> cycle_members;

    for (const auto& entry : relationships) {
        const string& employee_id = entry.first;
        if (visited.find(employee_id) != visited.end()) {
            continue;
        }

        vector<string> path;
        unordered_map<string, int> positions;
        string current = employee_id;

        while (relationships.find(current) != relationships.end() &&
               visited.find(current) == visited.end()) {
            if (positions.find(current) != positions.end()) {
                int cycle_start = positions[current];
                for (size_t index = cycle_start; index < path.size(); index++) {
                    cycle_members.insert(path[index]);
                }
                break;
            }

            positions[current] = static_cast<int>(path.size());
            path.push_back(current);
            current = relationships.at(current);
        }

        for (const string& id : path) {
            visited.insert(id);
        }
    }

    return cycle_members;
}

PreviewResult analyze_csv(const string& upload) {
    vector<pair<int, unordered_map<string, string>>> rows = parse_rows(upload);

    vector<Employee> employees;
    employees.reserve(rows.size());
    for (const auto& row : rows) {
        employees.push_back(normalize_row(row.first, row.second));
    }

    vector<RowIssue> errors;
    unordered_set<int> invalid_identity_rows;
    unordered_map<string, vector<const Employee*>> ids;
    unordered_map<string, vector<const Employee*>> emails;

    for (const Employee& employee : employees) {
        if (employee.employee_id.empty()) {
            errors.push_back({employee.row_number, "employee_id is required."});
            invalid_identity_rows.insert(employee.row_number);
        } else {
            ids[employee.employee_id].push_back(&employee);
        }

        if (employee.email.empty()) {
            errors.push_back({employee.row_number, "email is required."});
            invalid_identity_rows.insert(employee.row_number);
        } else {
            emails[employee.email].push_back(&employee);
        }
    }

    for (const auto& entry : ids) {
        const string& duplicate_id = entry.first;
        const vector<const Employee*>& duplicates = entry.second;
        if (duplicates.size() > 1) {
            for (const Employee* employee : duplicates) {
                errors.push_back({employee->row_number,
                                  "employee_id '" + duplicate_id + "' is duplicated."});
                invalid_identity_rows.insert(employee->row_number);
            }
        }
    }

    for (const auto& entry : emails) {
        const string& duplicate_email = entry.first;
        const vector<const Employee*>& duplicates = entry.second;
        if (duplicates.size() > 1) {
            for (const Employee* employee : duplicates) {
                errors.push_back({employee->row_number,
                                  "email '" + duplicate_email + "' is duplicated."});
                invalid_identity_rows.insert(employee->row_number);
            }
        }
    }

    vector<Employee> accepted;
    for (const Employee& employee : employees) {
        if (invalid_identity_rows.find(employee.row_number) == invalid_identity_rows.end()) {
            accepted.push_back(employee);
        }
    }

    unordered_map<string, const Employee*> by_id;
    unordered_map<string, const Employee*> by_email;
    for (const Employee& employee : accepted) {
        by_id[employee.employee_id] = &employee;
        by_email[employee.email] = &employee;
    }

    vector<Employee> roots;
    unordered_map<string, string> relationships;
    unordered_map<string, vector<Employee>> direct_reports;
    for (const Employee& employee : accepted) {
        direct_reports[employee.employee_id] = {};
    }

    for (const Employee& employee : accepted) {
        auto resolved = resolve_manager(employee, by_id, by_email);
        const Employee* manager = resolved.first;
        const string& manager_error = resolved.second;

        if (!manager_error.empty()) {
            errors.push_back({employee.row_number, manager_error});
            continue;
        }

        if (manager == nullptr) {
            roots.push_back(employee);
            continue;
        }

        relationships[employee.employee_id] = manager->employee_id;
        direct_reports[manager->employee_id].push_back(employee);
    }

    vector<ManagerSummary> managers;
    for (const Employee& manager : accepted) {
        const vector<Employee>& reports = direct_reports[manager.employee_id];
        if (!reports.empty()) {
            managers.push_back({
                manager.employee_id,
                manager.employee_name,
                manager.email,
                static_cast<int>(reports.size()),
            });
        }
    }

    sort(managers.begin(), managers.end(), [](const ManagerSummary& left, const ManagerSummary& right) {
        if (left.direct_report_count != right.direct_report_count) {
            return left.direct_report_count > right.direct_report_count;
        }

        string left_name = lowercase(left.employee_name);
        string right_name = lowercase(right.employee_name);
        return left_name < right_name;
    });

    unordered_set<string> cycle_ids = find_cycle_members(relationships);
    unordered_map<string, Employee> accepted_by_id;
    for (const Employee& employee : accepted) {
        accepted_by_id[employee.employee_id] = employee;
    }

    vector<Employee> cycle_employees;
    for (const string& employee_id : cycle_ids) {
        cycle_employees.push_back(accepted_by_id[employee_id]);
    }
    sort(cycle_employees.begin(), cycle_employees.end(), [](const Employee& left, const Employee& right) {
        return left.row_number < right.row_number;
    });

    sort(errors.begin(), errors.end(), [](const RowIssue& left, const RowIssue& right) {
        if (left.row_number != right.row_number) {
            return left.row_number < right.row_number;
        }
        return left.message < right.message;
    });

    sort(roots.begin(), roots.end(), [](const Employee& left, const Employee& right) {
        return left.row_number < right.row_number;
    });

    return PreviewResult{
        static_cast<int>(rows.size()),
        accepted,
        errors,
        roots,
        managers,
        cycle_employees,
        relationships,
    };
}

int main() {
    string sample =
        "employee_id,employee_name,email,manager_id,manager_email,department\n"
        "CEO1,Chris CEO,chris@example.com,,,Executive\n"
        "M1,Mina Manager,MINA@example.com,CEO1,,People\n"
        "E1,Eli Employee,eli@example.com,,mina@example.com,People\n"
        "E2,Robin Report,robin@example.com,M1,mina@example.com,People\n"
        "DUP,Duplicate One,dupe1@example.com,,,Sales\n"
        "DUP,Duplicate Two,dupe2@example.com,,,Sales\n"
        "BAD1,Bad Manager,bad.manager@example.com,UNKNOWN,,Operations\n"
        "SELF1,Self Manager,self@example.com,SELF1,,Operations\n"
        "C1,Cycle One,c1@example.com,C2,,Engineering\n"
        "C2,Cycle Two,c2@example.com,C1,,Engineering\n"
        "INTO1,Reports Into Cycle,into@example.com,C1,,Engineering\n";

    try {
        PreviewResult result = analyze_csv(sample);
        cout << "Source rows: " << result.total_source_rows << "\n";
        cout << "Accepted employees: " << result.accepted_employees.size() << "\n";
        cout << "Validation errors: " << result.row_errors.size() << "\n";
        cout << "Roots: " << result.roots.size() << "\n";
        cout << "Managers: " << result.managers.size() << "\n";
        cout << "Cycle members: " << result.cycle_employees.size() << "\n";
    } catch (const UploadParseError& error) {
        cerr << error.what() << "\n";
        return 1;
    }

    return 0;
}
