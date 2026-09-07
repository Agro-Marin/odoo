import typing

from odoo.orm.models.mixins.schema import SchemaMixin


class _Field:
    is_boolean = True
    required = False

    def __init__(self, default):
        self._default = default

    def default(self, model):
        return self._default

    def convert_to_write(self, value, model):
        return value

    def convert_to_column_insert(self, value, model):
        return value


class _Cursor:
    def __init__(self):
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((" ".join(str(query.code).split()), tuple(query.params)))


class _Env:
    def __init__(self):
        self.cr = _Cursor()


def _model(default):
    class _Model(SchemaMixin):
        _table = "res_company"
        _fields = {"active": _Field(default)}
        env = _Env()

    return typing.cast("typing.Any", object.__new__(_Model))


def test_a_new_boolean_column_backfills_every_row():
    # create_column gives a boolean column DEFAULT false, so a `WHERE active IS
    # NULL` backfill matched nothing and the main company stayed inactive on a
    # fresh install: every user creation then failed its company check.
    model = _model(default=True)
    model._init_column("active", new_column=True)
    assert model.env.cr.executed == [
        ('UPDATE "res_company" SET "active" = %s', (True,)),
    ]


def test_an_existing_column_only_fills_the_nulls():
    model = _model(default=True)
    model._init_column("active")
    assert model.env.cr.executed == [
        ('UPDATE "res_company" SET "active" = %s WHERE "active" IS NULL', (True,)),
    ]


def test_a_boolean_default_of_false_needs_no_backfill():
    model = _model(default=False)
    model._init_column("active", new_column=True)
    assert model.env.cr.executed == []
