import textwrap
from pathlib import Path

import pytest
from compute_context_deps import Violation, declared_keys, measure, read_keys


def _func(src: str):
    import ast

    return next(
        n
        for n in ast.walk(ast.parse(textwrap.dedent(src)))
        if isinstance(n, ast.FunctionDef)
    )


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("self.env.user", {"uid"}),
        ("self.env.uid", {"uid"}),
        ("record.env.user.partner_id.id", {"uid"}),
        ('cr.execute(q, {"pid": self.env.user.partner_id.id})', {"uid"}),
        ('self.env["mail.guest"]._get_guest_from_context()', {"guest"}),
        ("self.env.company", set()),
        ("self.env.companies", set()),
        ('self.env["res.partner"].search([])', set()),
        ("self.user_id.name", set()),
        ("env.user.partner_id", {"uid"}),
        ("get_lang(self.env).code", {"lang"}),
        ("get_lang(self.env).week_start", {"lang"}),
        ("format_date(self.env, self.date)", {"lang"}),
        ("format_amount(self.env, 1.0, self.currency_id)", {"lang"}),
        ("format_list(self.env, [1, 2])", {"lang"}),
        ("format_datetime(self.env, self.date)", {"lang"}),
        ('dict(self._fields["state"]._description_selection(self.env))', {"lang"}),
        (
            'list(dict(self._fields["state"]._description_selection(self.env)))',
            set(),
        ),
        (
            'dict(self._fields["state"]._description_selection(self.env)).keys()',
            set(),
        ),
        ("format_duration(self.duration)", set()),
    ],
)
def test_read_keys(body, expected):
    node = _func(f"""
        def _compute_x(self):
            {body}
    """)
    assert read_keys(node) == expected


@pytest.mark.parametrize(
    ("decorators", "expected"),
    [
        (['@api.depends_context("uid")'], {"uid"}),
        (["@api.depends_context('uid', 'company')"], {"uid", "company"}),
        (['@api.depends("x")', '@api.depends_context("uid")'], {"uid"}),
        (['@api.depends_context("uid")', '@api.depends("x")'], {"uid"}),
        (['@api.depends("x")'], set()),
        (["@api.model"], set()),
        ([], set()),
    ],
)
def test_declared_keys(decorators, expected):
    src = "\n".join([*decorators, "def _compute_x(self):", "    return self.env.user"])
    assert declared_keys(_func(src)) == expected


def _write(tmp_path: Path, name: str, src: str) -> Path:
    root = tmp_path / "addons" / "probe" / "models"
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(textwrap.dedent(src), encoding="utf-8")
    return path


def test_a_declared_lang_is_quiet(tmp_path):
    (tmp_path / "m.py").write_text(
        textwrap.dedent("""
            class M:
                @api.depends_context("lang")
                def _compute_label(self):
                    self.label = get_lang(self.env).code
        """)
    )
    assert measure([tmp_path]) == []


def test_a_lang_read_and_a_uid_read_are_two_findings(tmp_path):
    (tmp_path / "m.py").write_text(
        textwrap.dedent("""
            class M:
                def _compute_label(self):
                    self.label = get_lang(self.env).code + self.env.user.name
        """)
    )
    assert [v.key for v in measure([tmp_path])] == ["lang", "uid"]


def test_measure_flags_an_undeclared_read(tmp_path):
    _write(
        tmp_path,
        "m.py",
        """
        class M(models.Model):
            @api.depends("x")
            def _compute_flag(self):
                for r in self:
                    r.flag = r.user_id == self.env.user
        """,
    )
    found = measure([tmp_path])
    assert [(v.method, v.key) for v in found] == [("_compute_flag", "uid")]


def test_measure_is_quiet_when_the_key_is_declared(tmp_path):
    _write(
        tmp_path,
        "m.py",
        """
        class M(models.Model):
            @api.depends("x")
            @api.depends_context("uid")
            def _compute_flag(self):
                for r in self:
                    r.flag = r.user_id == self.env.user
        """,
    )
    assert measure([tmp_path]) == []


def test_measure_only_looks_at_compute_methods(tmp_path):
    _write(
        tmp_path,
        "m.py",
        """
        class M(models.Model):
            def action_do_thing(self):
                return self.env.user

            def _search_flag(self, operator, value):
                return [("user_id", "=", self.env.user.id)]
        """,
    )
    assert measure([tmp_path]) == []


def test_measure_skips_tests(tmp_path):
    _write(
        tmp_path,
        "clean.py",
        """
        class M(models.Model):
            def _compute_x(self):
                self.x = 1
    """,
    )
    root = tmp_path / "addons" / "probe" / "tests"
    root.mkdir(parents=True)
    (root / "test_thing.py").write_text(
        textwrap.dedent("""
            class T(TransactionCase):
                def _compute_helper(self):
                    return self.env.user
        """),
        encoding="utf-8",
    )
    assert measure([tmp_path]) == []


def test_measure_refuses_an_empty_tree(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(RuntimeError, match="refusing to report a count"):
        measure([tmp_path / "empty"])


def test_violation_is_sortable_and_prints_its_location(tmp_path):
    v = Violation(
        file="addons/probe/models/m.py", line=12, method="_compute_x", key="uid"
    )
    assert "addons/probe/models/m.py:12" in str(v)
    assert v.key in str(v)


def test_measure_orders_by_key_then_location(tmp_path):
    _write(
        tmp_path,
        "b.py",
        """
        class B(models.Model):
            def _compute_guest(self):
                return self.env["mail.guest"]._get_guest_from_context()
        """,
    )
    _write(
        tmp_path,
        "a.py",
        """
        class A(models.Model):
            def _compute_user(self):
                return self.env.user
        """,
    )
    keys = [v.key for v in measure([tmp_path])]
    assert keys == sorted(keys)
