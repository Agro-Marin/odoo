{
    "name": "Timesheets/attendances reporting",
    "version": "1.1",
    "category": "Human Resources/Attendances",
    "description": """
    Module linking the attendance module to the timesheet app.
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "hr_timesheet",
        "hr_attendance",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/hr_timesheet_attendance_report_security.xml",
        "report/hr_timesheet_attendance_report_view.xml",
    ],
    "auto_install": True,
}
