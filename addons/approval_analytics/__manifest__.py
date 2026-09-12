{
    "name": "Approval Analytics",
    "version": "19.0.1.0.0",
    "category": "Human Resources/Approvals",
    "sequence": 191,
    "summary": "Category and approver statistics over the approval engine",
    "description": """
Approval Analytics
==================

The two materialized reports the approval engine is measured by, and the
menu entries that open them.

Models
------
* ``approval.metrics`` -- per category: approval rate, average and median
  time, SLA compliance, cancelled count
* ``approver.performance`` -- per approver: response time, approval rate,
  workload

Both are SQL views over ``approval.request`` and ``approval.approver``
through ``mixin.sql.report``, which owns the materialized-view lifecycle and
its cron. That dependency is why they are not in ``approval``: a module
adopting ``mixin.approval`` needs the engine, not the reporting stack.
""",
    "author": "AgroMarin",
    "license": "LGPL-3",
    "depends": [
        "approval",
        "mixin_report_sql",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/ir_rule.xml",
        "views/approval_dashboard_views.xml",
        "views/approval_metrics_views.xml",
        "views/approver_performance_views.xml",
        "views/approval_analytics_menuitem_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "approval_analytics/static/src/scss/approval_dashboard.scss",
        ],
        "web.assets_web_dark": [
            "approval_analytics/static/src/scss/approval_dashboard.dark.scss",
        ],
    },
    "auto_install": True,
}
