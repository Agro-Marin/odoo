from types import SimpleNamespace

from odoo import Command
from odoo.tests import common, tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class _FakeAccount:
    """Identity-hashable stand-in for an account record."""

    # The planner uses accounts as dict keys; ``SimpleNamespace`` cannot serve
    # because it defines ``__eq__`` and is therefore unhashable.
    def __init__(self, id_, currency_id=False):
        self.id = id_
        self.currency_id = currency_id


@tagged("post_install", "-at_install")
class TestResCompanyAccountCode(AccountTestInvoicingCommon):
    """Pins ``get_new_account_code`` and ``reflect_code_prefix_change``."""

    # The cases below document the real behaviour of the ``lstrip('0')`` /
    # ``rjust`` transform: the code length survives only while the new prefix and
    # the zero-stripped tail still fit in it.
    def test_get_new_account_code_pure(self):
        new_code = self.env["res.company"].get_new_account_code
        cases = {
            # (current, old_prefix, new_prefix): expected
            ("101000", "1", "2"): "201000",  # same-length swap, tail kept
            ("101000", "10", "20"): "201000",  # multi-char same-length swap
            ("511001", "511", "512"): "512001",  # real bank-prefix style swap
            ("570", "5", "512"): "51270",  # new prefix longer -> grows
            ("500", "5", "5000000"): "5000000",  # prefix > code -> tail absorbed
            ("5", "5", "6"): "6",  # whole tail consumed
        }
        for (code, old, new), expected in cases.items():
            self.assertEqual(
                new_code(code, old, new),
                expected,
                f"get_new_account_code({code!r}, {old!r}, {new!r})",
            )

    def test_get_new_account_code_length_preserved_for_same_length_prefix(self):
        """A same-length prefix the code starts with round-trips to the same length."""
        # ``reflect_code_prefix_change`` only feeds codes matched by its
        # ``=like old%`` search, so the old prefix is always present.
        new_code = self.env["res.company"].get_new_account_code
        for code in ("511001", "511999", "511000", "511100"):
            self.assertEqual(len(new_code(code, "511", "622")), len(code))

    def test_reflect_code_prefix_change(self):
        company = self.company_data["company"]
        Account = self.env["account.account"].with_company(company)
        cash_a = Account.create(
            {"name": "Cash A", "code": "511001", "account_type": "asset_cash"}
        )
        cash_b = Account.create(
            {"name": "Cash B", "code": "511050", "account_type": "asset_cash"}
        )
        # An account outside the cash/credit-card scope must stay untouched.
        other = Account.create(
            {"name": "Other 511", "code": "511900", "account_type": "expense"}
        )

        company.reflect_code_prefix_change("511", "622")

        self.assertEqual(cash_a.code, "622001")
        self.assertEqual(cash_b.code, "622050")
        self.assertEqual(other.code, "511900", "non-cash account must be untouched")

    def test_reflect_code_prefix_change_noop(self):
        company = self.company_data["company"]
        cash = (
            self.env["account.account"]
            .with_company(company)
            .create({"name": "Cash", "code": "511001", "account_type": "asset_cash"})
        )
        company.reflect_code_prefix_change("511", "511")  # same -> no-op
        company.reflect_code_prefix_change(False, "622")  # falsy old -> no-op
        self.assertEqual(cash.code, "511001")


@tagged("post_install", "-at_install")
class TestUnaffectedEarningsAccount(AccountTestInvoicingCommon):
    """Pins ``get_unaffected_earnings_account`` code selection."""

    # The fallback counting down from 999999 is never exercised by a standard
    # chart of accounts: it already ships an ``equity_unaffected`` account, so
    # the method returns early.
    def _fresh_company(self, name):
        # A company with no chart template: no equity_unaffected account exists,
        # forcing get_unaffected_earnings_account down its creation path.
        return self.env["res.company"].create({"name": name})

    def test_returns_existing_unaffected_account(self):
        company = self.company_data["company"]
        existing = (
            self.env["account.account"]
            .with_company(company)
            .search(
                [
                    *self.env["account.account"]._check_company_domain(company),
                    ("account_type", "=", "equity_unaffected"),
                ],
                limit=1,
            )
        )
        self.assertTrue(existing, "the test chart is expected to ship one")
        self.assertEqual(company.get_unaffected_earnings_account(), existing)

    def test_creates_999999_when_free(self):
        company = self._fresh_company("Unaffected Fresh")
        account = company.get_unaffected_earnings_account()
        self.assertEqual(account.account_type, "equity_unaffected")
        # `code` is company-dependent -> read it under this company.
        self.assertEqual(account.with_company(company).code, "999999")

    def test_skips_taken_codes_counting_down(self):
        company = self._fresh_company("Unaffected Collision")
        Account = self.env["account.account"].with_company(company)
        # Occupy 999999 and 999998 with unrelated accounts.
        for code in ("999999", "999998"):
            Account.create(
                {
                    "name": f"Occupant {code}",
                    "code": code,
                    "account_type": "expense",
                    "company_ids": [Command.link(company.id)],
                }
            )
        account = company.get_unaffected_earnings_account()
        self.assertEqual(account.account_type, "equity_unaffected")
        self.assertEqual(
            account.with_company(company).code,
            "999997",
            "must skip the taken codes",
        )
        # Idempotent: a second call returns the same account, no new code burned.
        self.assertEqual(company.get_unaffected_earnings_account(), account)


@tagged("post_install", "-at_install")
class TestResCompanyDomesticFP(common.TransactionCase):
    """Pins the ordering of ``_compute_domestic_fiscal_position_id``."""

    def setUp(self):
        super().setUp()
        self.be = self.env.ref("base.be")
        self.europe = self.env.ref("base.europe")
        self.company = self.env["res.company"].create(
            {"name": "CC Domestic", "country_id": self.be.id}
        )
        self.FP = self.env["account.fiscal.position"].with_company(self.company)

    def _fp(self, name, sequence, specific):
        return self.FP.create(
            {
                "name": name,
                "company_id": self.company.id,
                "sequence": sequence,
                "country_id": self.be.id if specific else False,
                "country_group_id": False if specific else self.europe.id,
            }
        )

    def test_lowest_sequence_wins_over_specificity(self):
        self._fp("spec-seq5", 5, specific=True)
        group_low = self._fp("group-seq1", 1, specific=False)
        self.company.invalidate_recordset(["domestic_fiscal_position_id"])
        self.assertEqual(self.company.domestic_fiscal_position_id, group_low)

    def test_specific_beats_group_on_sequence_tie(self):
        # group created first (earlier in the recordset) to prove the tiebreak
        # is by country specificity, not insertion order.
        self._fp("group-seq5", 5, specific=False)
        spec = self._fp("spec-seq5", 5, specific=True)
        self.company.invalidate_recordset(["domestic_fiscal_position_id"])
        self.assertEqual(self.company.domestic_fiscal_position_id, spec)

    def test_no_candidate(self):
        self.assertFalse(self.company.domestic_fiscal_position_id)


@tagged("post_install", "-at_install")
class TestResCompanyMultiVat(common.TransactionCase):
    """Pins that ``multi_vat_foreign_country_ids`` tracks the position country."""

    # Guards the ``fiscal_position_ids.country_id`` entry of the ``@api.depends``
    # on ``_compute_multi_vat_foreign_country``.
    def test_multi_vat_follows_country_id(self):
        be = self.env.ref("base.be")
        fr = self.env.ref("base.fr")
        us = self.env.ref("base.us")
        company = self.env["res.company"].create(
            {"name": "CC MultiVat", "country_id": us.id}
        )
        company.account_fiscal_country_id = us
        fp = self.env["account.fiscal.position"].create(
            {
                "name": "BE foreign VAT",
                "company_id": company.id,
                "country_id": be.id,
                "foreign_vat": "BE0477472701",
            }
        )
        self.assertEqual(company.multi_vat_foreign_country_ids, be)

        # Moving the position to FR (foreign_vat stays 'BE0477472701') must be
        # reflected in the computed country set.
        fp.write({"country_id": fr.id})
        self.assertEqual(company.multi_vat_foreign_country_ids, fr)


@tagged("post_install", "-at_install")
class TestOpeningMovePlanner(common.TransactionCase):
    """DB-free unit tests for the pure planner ``_plan_opening_move_lines``."""

    # Records and currency are faked. Command tuples are ``(0, 0, vals)`` create,
    # ``(1, id, vals)`` update, ``(2, id, 0)`` delete.

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.a1 = _FakeAccount(1)
        cls.a2 = _FakeAccount(2)
        cls.bal = _FakeAccount(9)

    def _plan(self, to_update, existing=None, initial=0.0):
        return self.env["res.company"]._plan_opening_move_lines(
            to_update=to_update,
            balancing_account=self.bal,
            existing_lines=existing or {},
            initial_balance=initial,
            is_zero=lambda balance: abs(balance) < 1e-9,
            amount_currency_of=lambda account, balance: balance,
            currency_id_of=lambda account: 42,
            opening_name="OPEN",
            balancing_name="BAL",
        )

    @staticmethod
    def _line(id_, balance):
        return SimpleNamespace(id=id_, balance=balance)

    def test_fresh_single_debit_balances_to_zero(self):
        cmds = self._plan({self.a1: (100.0, None)})
        self.assertEqual(len(cmds), 2, "one opening line + one balancing line")
        creates = {c[2]["account_id"]: c[2] for c in cmds if c[0] == 0}
        self.assertEqual(sum(v["balance"] for v in creates.values()), 0.0)
        self.assertEqual(creates[1]["balance"], 100.0)
        self.assertEqual(creates[1]["name"], "OPEN")
        self.assertEqual(creates[9]["balance"], -100.0)
        self.assertEqual(creates[9]["name"], "BAL")
        self.assertEqual(creates[9]["currency_id"], 42)

    def test_fresh_debit_and_credit(self):
        cmds = self._plan({self.a1: (100.0, 30.0)})
        creates = [c[2] for c in cmds if c[0] == 0]
        self.assertEqual(sum(v["balance"] for v in creates), 0.0)
        a1_balances = sorted(v["balance"] for v in creates if v["account_id"] == 1)
        self.assertEqual(a1_balances, [-30.0, 100.0], "credit stored as negative")

    def test_update_replaces_existing_and_rebalances(self):
        existing = {
            (self.a1, "debit"): [self._line(7, 40.0)],
            (self.bal, "credit"): [self._line(8, -40.0)],
        }
        cmds = self._plan({self.a1: (100.0, None)}, existing=existing, initial=40.0)
        self.assertTrue(all(c[0] == 1 for c in cmds), "only updates, no create/delete")
        updates = {c[1]: c[2] for c in cmds if c[0] == 1}
        self.assertEqual(updates[7]["balance"], 100.0)
        self.assertEqual(updates[8]["balance"], -100.0)
        self.assertEqual(updates[7]["balance"] + updates[8]["balance"], 0.0)

    def test_zero_side_deletes_existing_lines(self):
        existing = {
            (self.a1, "debit"): [self._line(7, 100.0)],
            (self.bal, "credit"): [self._line(8, -100.0)],
        }
        cmds = self._plan({self.a1: (0.0, None)}, existing=existing, initial=100.0)
        self.assertEqual({c[1] for c in cmds if c[0] == 2}, {7, 8})
        self.assertFalse([c for c in cmds if c[0] == 0], "nothing created")


@tagged("post_install", "-at_install")
class TestUpdateOpeningMove(AccountTestInvoicingCommon):
    """End-to-end: ``_update_opening_move`` creates/updates a balanced move."""

    def test_create_then_update_stays_balanced(self):
        company = self.company_data["company"]
        revenue = self.company_data["default_account_revenue"]
        expense = self.company_data["default_account_expense"]

        company._update_opening_move({revenue: (1000.0, 0.0), expense: (0.0, 400.0)})
        move = company.account_opening_move_id
        self.assertTrue(move, "opening move created")
        self.assertEqual(sum(move.line_ids.mapped("balance")), 0.0, "balanced")
        self.assertEqual(
            sum(move.line_ids.mapped("debit")), sum(move.line_ids.mapped("credit"))
        )
        self.assertEqual(
            move.line_ids.filtered(lambda ln: ln.account_id == revenue).balance, 1000.0
        )

        # Re-run to update one account: the move must stay balanced.
        company._update_opening_move({revenue: (500.0, 0.0)})
        self.assertEqual(sum(move.line_ids.mapped("balance")), 0.0)
        self.assertEqual(
            move.line_ids.filtered(lambda ln: ln.account_id == revenue).balance, 500.0
        )
