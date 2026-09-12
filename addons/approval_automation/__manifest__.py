{
    "name": "Approval Automation",
    "version": "19.0.1.0.0",
    "category": "Human Resources/Approvals",
    "sequence": 192,
    "summary": "Automation rules an approval category runs, and Reset When on a binding",
    "description": """
Approval Automation
===================

Everything in the approval engine that reaches ``automation``, kept out of
``approval`` so that adopting ``mixin.approval`` does not pull the automation
stack -- ``bus``, ``credential``, ``digest``, ``resource``, ``sms``, ``iap``
and ``iap_mail`` -- into a module that only wants to raise approval requests.

What it adds
------------
* ``approval.category.automation_id`` and ``has_automation`` -- the flow a
  request of this category runs, and whether naming it is required
* ``approval.request.automation_runtime_id`` -- the run that flow produced
* ``approval.binding.reset_domain`` / ``reset_automation_id`` -- Reset When:
  one managed ``automation.rule`` per binding, firing on a record's transition
  INTO the condition, which resets the approvals that covered it

``_reset_coverage`` itself stays in ``approval``: deciding which requests a
reset clears is engine logic, and only the trigger needs ``automation``.
""",
    "author": "AgroMarin",
    "license": "LGPL-3",
    "depends": [
        "approval",
        "automation",
    ],
    "data": [
        "views/approval_automation_views.xml",
    ],
    "auto_install": True,
}
