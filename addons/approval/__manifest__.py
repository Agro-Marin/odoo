{
    "name": "Base Approval",
    "version": "19.0.1.0.25",
    "category": "Human Resources/Approvals",
    "sequence": 190,
    "summary": "Create and validate approval requests with delegation and escalation",
    "description": """
Base Approval
=============

Approval requests with configurable categories, multi-level approvers,
delegation and escalation.

Models
------
* ``approval.request`` / ``approval.approver`` -- the request and its approvers
* ``approval.category`` / ``approval.category.approver`` -- request types and
  their default approvers
* ``approval.rule`` / ``mixin.approval.threshold`` -- routing by amount,
  quantity, date range or priority; adding or replacing approvers
* ``mixin.approval`` -- puts the workflow on any model
* ``approval.document.requirement`` -- documents a category demands
* ``approval.template`` -- reusable request presets
* ``approval.delegate.wizard`` / ``approval.decision.wizard`` /
  ``approval.refusal.reason`` -- delegation, decisions, refusal reasons

A request creates an activity for each approver. Delegation reassigns those
activities to a substitute for a dated window; escalation reminds by priority.
""",
    "author": "AgroMarin",
    "license": "LGPL-3",
    "depends": [
        "base_automation",
        "base_sql_report",
        "mail",
    ],
    "data": [
        "security/res_groups.xml",
        "security/ir_rule.xml",
        "security/ir.model.access.csv",
        "data/ir_config_parameter_data.xml",
        "data/approval_category_data.xml",
        "data/mail_activity_type_data.xml",
        "data/mail_message_subtype_data.xml",
        "data/ir_cron_data.xml",
        "data/approval_refusal_reason_data.xml",
        "report/approval_request_report.xml",
        "views/approval_category_views.xml",
        "views/approval_category_approver_views.xml",
        "views/approval_request_views.xml",
        "views/approval_refusal_reason_views.xml",
        "views/approval_template_views.xml",
        "views/approval_rule_views.xml",
        "views/approval_document_requirement_views.xml",
        "views/approval_request_template.xml",
        "report/approval_metrics_views.xml",
        "report/approver_performance_views.xml",
        "report/approval_dashboard_views.xml",
        "wizard/approval_decision_wizard_views.xml",
        "wizard/approval_delegate_wizard_views.xml",
        "views/res_users_views.xml",
        "views/approvals_menuitem_views.xml",
    ],
    "demo": [
        "demo/00_approval_users_demo.xml",
        "demo/01_approval_groups_demo.xml",
        "demo/approval_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "approval/static/src/common/**",
            "approval/static/src/web/**",
            "approval/static/src/views/**",
            "approval/static/src/scss/**",
            (
                "remove",
                "approval/static/src/scss/*.dark.scss",
            ),
        ],
        "web.assets_web_dark": [
            "approval/static/src/scss/approval_dashboard.dark.scss",
            "approval/static/src/scss/approval.dark.scss",
        ],
        "mail.assets_public": [
            "approval/static/src/common/**",
        ],
        "web.assets_tests": [
            "approval/static/tests/tours/**/*",
        ],
        "web.assets_unit_tests": [
            "approval/static/tests/**/*",
            (
                "remove",
                "approval/static/tests/tours/**/*",
            ),
        ],
    },
    "application": True,
}
