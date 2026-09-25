from odoo import api, fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_recompute_expansion_protected_dbfree"


class Payment(models.Model):
    _name = "rep.payment"
    _module = _MOD
    _description = "a state whose compute reads a peer's stored dependent"
    _log_access = False

    amount = fields.Integer()
    flag = fields.Boolean()
    peer_id = fields.Many2one(comodel_name="rep.payment")
    state = fields.Char(compute="_compute_state", store=True)
    matched = fields.Boolean(compute="_compute_matched", store=True)

    @api.depends("amount")
    def _compute_state(self):
        for payment in self:
            payment.peer_id.mapped("matched")
            payment.state = "paid" if payment.amount >= 10 else "open"

    @api.depends("state", "flag")
    def _compute_matched(self):
        for payment in self:
            payment.matched = payment.state == "paid"


def test_a_batch_leaves_out_the_records_whose_dependency_is_mid_compute():
    with model_test_env(Payment) as env:
        peer = env["rep.payment"].create({"amount": 0})
        payment = env["rep.payment"].create({"amount": 0, "peer_id": peer.id})
        env.flush_all()
        assert (payment.state, payment.matched) == ("open", False)

        payment.amount = 20
        peer.flag = True

        assert payment.state == "paid"
        assert payment.matched is True
        assert peer.matched is False


def test_a_batch_still_expands_over_records_nothing_is_computing():
    with model_test_env(Payment) as env:
        first, second = env["rep.payment"].create([{"amount": 20}, {"amount": 30}])
        env.flush_all()
        first.flag = second.flag = True

        first.matched
        assert not env.is_to_compute(first._fields["matched"], second)
        assert (first.matched, second.matched) == (True, True)
