from odoo.tests import common


def isolate_group_approval_manager(env, keep=None):
    keep = keep if keep is not None else env["res.users"]
    group = env.ref("approval.group_approval_manager")
    if "res.users.role" in env.registry:
        roles = env["res.users.role"].search([("implied_ids", "in", group.id)])
        if roles:
            for role in roles:
                role.implied_ids = [(3, group.id)]
            env["res.users.role"].search([]).update_users()

    company = env.company
    others = env["res.users"].search(
        [
            ("group_ids", "in", group.id),
            ("company_ids", "in", company.id),
            ("id", "not in", keep.ids),
        ],
    )
    if others:
        others.write({"group_ids": [(3, group.id)]})


class ApprovalCommon(common.TransactionCase):
    _seq_code_counter = 0

    @classmethod
    def _next_sequence_code(cls):
        ApprovalCommon._seq_code_counter += 1
        return f"TC{ApprovalCommon._seq_code_counter:04d}"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner_user = cls.env["res.users"].create(
            {
                "name": "Request Owner",
                "login": "approval_common_owner",
                "email": "owner@test.com",
            },
        )
        cls.approver_1 = cls.env["res.users"].create(
            {
                "name": "Approver One",
                "login": "approval_common_approver_1",
                "email": "approver1.common@test.com",
                "group_ids": [
                    (4, cls.env.ref("approval.group_approval_approver").id),
                ],
            },
        )
        cls.approver_2 = cls.env["res.users"].create(
            {
                "name": "Approver Two",
                "login": "approval_common_approver_2",
                "email": "approver2.common@test.com",
                "group_ids": [
                    (4, cls.env.ref("approval.group_approval_approver").id),
                ],
            },
        )
        cls.manager_user = cls.env["res.users"].create(
            {
                "name": "Approval Manager",
                "login": "approval_common_manager",
                "email": "manager.common@test.com",
                "group_ids": [
                    (4, cls.env.ref("approval.group_approval_manager").id),
                ],
            },
        )
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Approval Test Partner",
            },
        )

    @classmethod
    def _make_category(cls, name="Lifecycle Cat", code=None, approvers=None, **vals):
        code = code or cls._next_sequence_code()
        specs = [
            spec if isinstance(spec, tuple) else (spec, True, 10 * (index + 1))
            for index, spec in enumerate(approvers or ())
        ]
        required_count = sum(1 for _user, required, _sequence in specs if required)
        category = cls.env["approval.category"].create(
            {
                "name": name,
                "sequence_code": code,
                "approval_minimum": max(1, required_count),
                **vals,
            },
        )
        for user, required, sequence in specs:
            cls.env["approval.category.approver"].create(
                {
                    "category_id": category.id,
                    "user_id": user.id,
                    "required": required,
                    "sequence": sequence,
                },
            )
        return category

    @classmethod
    def _prepare_request(cls, category, confirm=True, owner=None, **vals):
        request = cls.env["approval.request"].create(
            {
                "category_id": category.id,
                "request_owner_id": (owner or cls.owner_user).id,
                "reason": "<p>lifecycle test</p>",
                **vals,
            },
        )
        if confirm:
            request.action_confirm()
        return request
