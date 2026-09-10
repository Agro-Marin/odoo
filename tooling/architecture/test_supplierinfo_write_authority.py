import supplierinfo_write_authority as swa


def _measure(tmp_path, body, module="mod", name="models/thing.py"):
    root = tmp_path / "addons"
    path = root / module / name
    path.parent.mkdir(parents=True, exist_ok=True)
    (root / module / "__manifest__.py").write_text("{}")
    path.write_text(body)
    return swa.measure([root])


def _shapes(tmp_path, body, **kwargs):
    return sorted(
        (w.function, w.shape, w.fields) for w in _measure(tmp_path, body, **kwargs)
    )


def test_create_on_the_model_names_its_price_fields(tmp_path):
    assert _shapes(
        tmp_path,
        "class A:\n"
        "    def f(self):\n"
        '        self.env["product.supplierinfo"].sudo().create({"price": 1, "partner_id": 2})\n',
    ) == [("A.f", "create", "price")]


def test_a_local_alias_of_the_model_is_followed(tmp_path):
    assert _shapes(
        tmp_path,
        "def f(env, vals):\n"
        '    Info = env["product.supplierinfo"]\n'
        "    Info.create(vals)\n",
    ) == [("f", "create", "payload not visible")]


def test_a_write_through_the_seller_relation_is_counted(tmp_path):
    assert _shapes(
        tmp_path,
        'def f(product):\n    product.seller_ids.write({"min_qty": 3})\n',
    ) == [("f", "write", "min_qty")]


def test_a_command_under_seller_ids_is_counted(tmp_path):
    assert _shapes(
        tmp_path,
        "def f(env):\n"
        '    env["product.template"].create({"seller_ids": [(0, 0, {"price": 5})]})\n',
    ) == [("f", "command under seller_ids", "price")]


def test_assigning_a_seller_list_is_counted(tmp_path):
    assert _shapes(
        tmp_path,
        'def f(product):\n    product.seller_ids = [Command.create({"date_end": d})]\n',
    ) == [("f", "assign seller_ids", "date_end")]


def test_assigning_a_price_on_a_seller_record_is_counted(tmp_path):
    assert _shapes(tmp_path, "def f(seller):\n    seller.discount = 5\n") == [
        ("f", "assign", "discount")
    ]


def test_non_price_fields_are_not_a_price_write(tmp_path):
    assert not _measure(
        tmp_path,
        'def f(product):\n    product.seller_ids.write({"product_code": "X", "delay": 3})\n',
    )


def test_an_unrelated_model_is_not_counted(tmp_path):
    assert not _measure(
        tmp_path,
        'def f(env):\n    env["product.pricelist.item"].create({"price": 1})\n',
    )


def test_tests_and_migrations_are_out_of_scope(tmp_path):
    body = 'def f(env):\n    env["product.supplierinfo"].create({"price": 1})\n'
    assert not _measure(tmp_path, body, name="tests/test_thing.py")
    assert not _measure(
        tmp_path, body, module="other", name="migrations/1.0/post-migrate.py"
    )


def test_a_listed_authority_is_not_unauthorised_and_an_unlisted_one_is(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(swa, "AUTHORITIES", {("mod", "A.f"): "owns the price"})
    found = _measure(
        tmp_path,
        "class A:\n"
        "    def f(self):\n"
        '        self.env["product.supplierinfo"].create({"price": 1})\n'
        "    def g(self):\n"
        '        self.env["product.supplierinfo"].create({"price": 2})\n',
    )
    unauthorised, stale = swa.split(found)
    assert [w.function for w in unauthorised] == ["A.g"]
    assert stale == []


def test_an_authority_that_stopped_writing_is_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(
        swa,
        "AUTHORITIES",
        {("mod", "A.f"): "owns the price", ("mod", "A.gone"): "moved"},
    )
    found = _measure(
        tmp_path,
        'class A:\n    def f(self):\n        self.env["product.supplierinfo"].create({"price": 1})\n',
    )
    assert swa.split(found) == ([], [("mod", "A.gone")])


def test_the_real_tree_holds_only_its_authorities():
    unauthorised, stale = swa.split(swa.measure())
    assert unauthorised == [], "\n".join(map(str, unauthorised))
    assert stale == []
