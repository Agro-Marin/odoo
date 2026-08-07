from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_check_company_batching"


class Thing(models.Model):
    _name = "ccb.thing"
    _module = _MOD
    _description = "thing"
    _log_access = False

    name = fields.Char()
    company_id = fields.Many2one("res.company")
    left_id = fields.Many2one("ccb.other", check_company=True)
    right_id = fields.Many2one("ccb.other", check_company=True)


class Other(models.Model):
    _name = "ccb.other"
    _module = _MOD
    _description = "other"
    _log_access = False

    name = fields.Char()
    company_id = fields.Many2one("res.company")


def _env():
    return model_test_env(Thing, Other)


def _violations(records):
    groups = records._check_company_candidates(["left_id", "right_id"], [])
    return [
        (rank, record.id, name, corecords.ids)
        for rank, record, name, corecords in sorted(
            records._check_company_violations(groups)
        )
    ]


def test_no_violation_when_companies_match():
    with _env() as env:
        other = env["ccb.other"].create({"name": "o", "company_id": 1})
        thing = env["ccb.thing"].create(
            {"name": "t", "company_id": 1, "left_id": other.id}
        )

        assert _violations(thing) == []


def test_violation_when_corecord_belongs_to_another_company():
    with _env() as env:
        elsewhere = env["res.company"].create({"name": "Elsewhere"})
        other = env["ccb.other"].create({"name": "o", "company_id": elsewhere.id})
        thing = env["ccb.thing"].create(
            {"name": "t", "company_id": 1, "left_id": other.id}
        )

        assert [(v[1], v[2]) for v in _violations(thing)] == [(thing.id, "left_id")]


def test_report_order_is_record_major_then_field_order():
    with _env() as env:
        elsewhere = env["res.company"].create({"name": "Elsewhere"})
        bad = env["ccb.other"].create({"name": "bad", "company_id": elsewhere.id})
        things = env["ccb.thing"].create(
            [
                {
                    "name": f"t{i}",
                    "company_id": 1,
                    "left_id": bad.id,
                    "right_id": bad.id,
                }
                for i in range(3)
            ]
        )

        reported = [(v[1], v[2]) for v in _violations(things)]

        assert reported == [
            (things[0].id, "left_id"),
            (things[0].id, "right_id"),
            (things[1].id, "left_id"),
            (things[1].id, "right_id"),
            (things[2].id, "left_id"),
            (things[2].id, "right_id"),
        ]


def test_records_of_different_companies_are_grouped_separately():
    with _env() as env:
        elsewhere = env["res.company"].create({"name": "Elsewhere"})
        here_other = env["ccb.other"].create({"name": "here", "company_id": 1})
        there_other = env["ccb.other"].create(
            {"name": "there", "company_id": elsewhere.id}
        )
        ok = env["ccb.thing"].create(
            {"name": "ok", "company_id": 1, "left_id": here_other.id}
        )
        bad = env["ccb.thing"].create(
            {"name": "bad", "company_id": 1, "left_id": there_other.id}
        )
        also_ok = env["ccb.thing"].create(
            {"name": "also", "company_id": elsewhere.id, "left_id": there_other.id}
        )

        groups = (ok + bad + also_ok)._check_company_candidates(["left_id"], [])

        assert len(groups) == 2
        reported = [(v[1], v[2]) for v in _violations(ok + bad + also_ok)]
        assert reported == [(bad.id, "left_id")]


def test_candidates_skip_empty_corecords():
    with _env() as env:
        thing = env["ccb.thing"].create({"name": "t", "company_id": 1})

        groups = thing._check_company_candidates(["left_id", "right_id"], [])

        assert groups == {}
