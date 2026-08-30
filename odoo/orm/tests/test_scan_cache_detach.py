import pytest

from odoo import api, fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_scan_cache_detach"

SOURCE: dict = {}
DETACH = {"on": False}


class ScanDetachWidget(models.Model):
    _name = "scan.detach.widget"
    _module = _MOD
    _description = "Scan Detach Widget"

    name = fields.Char()
    counter = fields.Integer(compute="_compute_from_source", store=False)
    flag = fields.Boolean(compute="_compute_from_source", store=False)

    @api.depends("name")
    def _compute_from_source(self):
        if DETACH["on"]:
            DETACH["on"] = False
            for key in SOURCE:
                SOURCE[key] += 100
            self.env.invalidate_all(flush=False)
        for record in self:
            record.counter = SOURCE[record.id]
            record.flag = SOURCE[record.id] % 200 >= 100


@pytest.fixture
def armed():
    SOURCE.clear()
    DETACH["on"] = False
    gen = model_test_env(ScanDetachWidget)
    env = gen.__enter__()
    records = env["scan.detach.widget"].create([{"name": f"w{i}"} for i in range(5)])
    for index, record in enumerate(records):
        SOURCE[record.id] = index + 1

    def arm(field_name):
        records.mapped(field_name)
        del records._fields[field_name]._get_cache(env)[records._ids[0]]
        DETACH["on"] = True
        return records

    def settled(field_name):
        DETACH["on"] = False
        env.invalidate_all(flush=False)
        return [record[field_name] for record in records]

    try:
        yield arm, settled
    finally:
        DETACH["on"] = False
        gen.__exit__(None, None, None)


def test_mapped_does_not_return_predetach_values(armed):
    arm, settled = armed
    records = arm("counter")
    got = records.mapped("counter")
    assert got == settled("counter")


def test_grouped_does_not_key_on_predetach_values(armed):
    arm, settled = armed
    records = arm("counter")
    got = sorted(records.grouped("counter"))
    assert got == sorted(settled("counter"))


def test_sorted_does_not_order_on_predetach_values(armed):
    arm, settled = armed
    records = arm("counter")
    got = records.sorted("counter DESC")._ids
    values = settled("counter")
    expected = tuple(
        rec_id
        for rec_id, _ in sorted(
            zip(records._ids, values, strict=True), key=lambda pair: -pair[1]
        )
    )
    assert got == expected


def test_filtered_does_not_drop_records_on_predetach_truthiness(armed):
    arm, settled = armed
    records = arm("flag")
    got = records.filtered("flag")._ids
    flags = settled("flag")
    expected = tuple(
        rec_id for rec_id, flag in zip(records._ids, flags, strict=True) if flag
    )
    assert got == expected


def test_read_does_not_return_predetach_values(armed):
    arm, settled = armed
    records = arm("counter")
    got = [vals["counter"] for vals in records.read(["counter"])]
    assert got == settled("counter")


def test_the_harness_is_not_vacuous(armed):
    arm, _settled = armed
    records = arm("counter")
    DETACH["on"] = False
    assert records.mapped("counter") == [1, 2, 3, 4, 5]
    assert sorted(records.grouped("counter")) == [1, 2, 3, 4, 5]
    assert records.filtered("counter")._ids == records._ids
