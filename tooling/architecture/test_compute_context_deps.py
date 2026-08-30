import textwrap
from pathlib import Path

import pytest
from compute_context_deps import (
    Violation,
    declared_keys,
    is_field_compute,
    measure,
    read_keys,
)


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


@pytest.mark.parametrize(
    ("signature", "expected"),
    [
        ("self", True),
        ("self, field_name", False),
        ("self, target_field=None", False),
        ("self, *args", False),
        ("self, **kwargs", False),
        ("self, *, key", False),
        ("providers_sudo, **kwargs", False),
    ],
)
def test_is_field_compute_takes_self_alone(signature, expected):
    node = _func(f"""
        def _compute_x({signature}):
            return self.env.user
    """)
    assert is_field_compute(node) is expected


def test_a_helper_named_compute_is_not_measured(tmp_path):
    _write(
        tmp_path,
        "m.py",
        """
        class M(models.Model):
            @api.model
            def _compute_domain(self, model_name, mode="read"):
                return self.env.uid
        """,
    )
    assert measure([tmp_path]) == []


@pytest.mark.parametrize(
    "body",
    [
        'dict(self._fields["type"]._description_selection(self.with_context({}).env))',
    ],
)
def test_a_read_through_a_stripped_context_is_not_a_read(body):
    node = _func(f"""
        def _compute_x(self):
            {body}
    """)
    assert read_keys(node) == set()


def test_a_name_bound_to_a_stripped_recordset_carries_the_strip():
    node = _func("""
        def _compute_complete_name(self):
            clean = self.with_context({}) if self.env.context else self
            labels = dict(self._fields["type"]._description_selection(clean.env))
            for record in clean:
                record.complete_name = labels[record.type]
    """)
    assert read_keys(node) == set()


def test_a_with_context_carrying_keys_does_not_neutralise():
    node = _func("""
        def _compute_x(self):
            other = self.with_context(lang="fr_FR")
            return get_lang(other.env).code
    """)
    assert read_keys(node) == {"lang"}


def test_a_helper_taking_more_than_self_is_not_a_field_compute(tmp_path):
    _write(
        tmp_path,
        "m.py",
        """
        class M(models.Model):
            @api.model
            def _compute_domain(self, model_name, mode="read"):
                return self.env.user.all_group_ids
        """,
    )
    assert measure([tmp_path]) == []


@pytest.mark.parametrize(
    "tail", ["target_field", "*names", "**kwargs", "*, group", "field_name, group"]
)
def test_no_signature_beyond_self_can_carry_depends_context(tmp_path, tail):
    _write(
        tmp_path,
        "m.py",
        f"""
        class M(models.Model):
            def _compute_warning(self, {tail}):
                return self.env.user.name
        """,
    )
    assert measure([tmp_path]) == []


def test_a_field_compute_taking_only_self_is_still_measured(tmp_path):
    _write(
        tmp_path,
        "m.py",
        """
        class M(models.Model):
            def _compute_flag(self):
                self.flag = self.env.user.name
        """,
    )
    assert [v.key for v in measure([tmp_path])] == ["uid"]


@pytest.mark.parametrize(
    "receiver",
    ["clean_self.env", "self.with_context({}).env"],
)
def test_a_selection_read_through_a_cleared_env_is_lang_free(receiver):
    node = _func(f"""
        def _compute_complete_name(self):
            clean_self = self.with_context({{}})
            labels = dict(self._fields["type"]._description_selection({receiver}))
    """)
    assert read_keys(node) == set()


@pytest.mark.parametrize(
    "clearing",
    [
        "self.with_context({}, lang=lang)",
        "self.with_context({'lang': lang})",
        "self.with_context(lang=lang)",
        "self.with_context()",
    ],
)
def test_only_an_empty_literal_with_no_overrides_clears_the_context(clearing):
    node = _func(f"""
        def _compute_complete_name(self):
            clean_self = {clearing}
            labels = dict(self._fields["type"]._description_selection(clean_self.env))
    """)
    assert read_keys(node) == {"lang"}


def test_a_cleared_env_does_not_excuse_the_methods_own_env():
    node = _func("""
        def _compute_label(self):
            clean_self = self.with_context({})
            labels = dict(self._fields["type"]._description_selection(clean_self.env))
            self.label = get_lang(self.env).code
    """)
    assert read_keys(node) == {"lang"}


def test_clearing_the_context_does_not_excuse_a_uid_read():
    node = _func("""
        def _compute_label(self):
            clean_self = self.with_context({})
            self.label = clean_self.env.user.name
    """)
    assert read_keys(node) == {"uid"}
