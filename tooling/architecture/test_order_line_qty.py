import order_line_qty as olq
import pytest


def _measure(tmp_path, body, name="thing.py"):
    root = tmp_path / "addons" / "mod"
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(body)
    return olq.measure([tmp_path / "addons"])


def _kinds(tmp_path, body):
    return sorted((w.kind, w.value) for w in _measure(tmp_path, body))


def test_a_stock_move_is_not_an_order_line(tmp_path):
    """The field is real and writable on `stock.move` — most matches are moves."""
    assert not _measure(
        tmp_path,
        'env["stock.move"].create({"product_id": p.id, "product_uom_qty": 5})\n',
    )


def test_a_move_under_move_ids_is_not_counted(tmp_path):
    assert not _measure(
        tmp_path,
        'env["stock.picking"].create(\n'
        '    {"move_ids": [(0, 0, {"product_id": p.id, "product_uom_qty": 5})]}\n'
        ")\n",
    )


def test_create_on_the_order_line_model_is_counted(tmp_path):
    assert _kinds(
        tmp_path,
        'env["sale.order.line"].create({"order_id": o.id, "product_uom_qty": 5})\n',
    ) == [("create", "5")]


def test_a_purchase_line_is_counted_too(tmp_path):
    assert _kinds(
        tmp_path,
        'env["purchase.order.line"].create({"product_uom_qty": 2.0})\n',
    ) == [("create", "2.0")]


def test_a_dict_under_line_ids_is_counted(tmp_path):
    assert _kinds(
        tmp_path,
        'env["sale.order"].create(\n'
        '    {"partner_id": 1, "line_ids": [(0, 0, {"product_uom_qty": 3})]}\n'
        ")\n",
    ) == [("create", "3")]


def test_a_bare_dict_naming_order_id_is_counted(tmp_path):
    """No model in sight, but `order_id` is not a field of `stock.move`'s vals."""
    assert _kinds(
        tmp_path,
        'Line.create({"order_id": order.id, "product_uom_qty": 7})\n',
    ) == [("create", "7")]


def test_a_create_of_one_is_counted(tmp_path):
    """Inert — the default absorbs it — and still the wrong field."""
    assert _kinds(
        tmp_path,
        'env["sale.order.line"].create({"product_uom_qty": 1})\n',
    ) == [("create", "1")]


def test_a_write_is_counted(tmp_path):
    assert _kinds(
        tmp_path,
        'order.line_ids.write({"product_uom_qty": 4})\n',
    ) == [("write", "4")]


def test_an_assignment_to_an_order_line_is_counted(tmp_path):
    assert _kinds(tmp_path, "sol.product_uom_qty = 0\n") == [("assign", "0")]


def test_an_assignment_to_a_move_is_not(tmp_path):
    assert not _measure(tmp_path, "move.product_uom_qty = 10\n")


def test_reading_the_field_is_not_a_write(tmp_path):
    assert not _measure(tmp_path, "qty = order.line_ids.product_uom_qty\n")


def test_one_line_is_reported_once(tmp_path):
    """A dict can match both the model rule and the `line_ids` rule."""
    assert (
        len(
            _measure(
                tmp_path,
                'env["sale.order"].create(\n'
                '    {"line_ids": [(0, 0, {"order_id": 1, "product_uom_qty": 9})]}\n'
                ")\n",
            )
        )
        == 1
    )


def test_a_file_that_does_not_parse_is_skipped(tmp_path):
    assert not _measure(tmp_path, "def (:\n", name="broken.py")


def test_a_missing_root_is_refused(tmp_path):
    """A typo in --roots must not read as a clean tree."""
    with pytest.raises(RuntimeError, match="no such directory"):
        olq.measure([tmp_path / "nope"])


def test_the_tree_measures_above_its_floor_shape():
    """The real tree parses and yields findings — the gate is not vacuous."""
    found = olq.measure()
    assert found, "the gate found nothing at all, which no longer matches the tree"
    assert all(w.path.endswith(".py") for w in found)


def test_a_name_that_merely_contains_sol_is_not_an_order_line(tmp_path):
    assert not _measure(tmp_path, "console.product_uom_qty = 3\n")


def test_a_filtered_order_line_set_is_still_order_lines(tmp_path):
    assert _kinds(
        tmp_path,
        'order.line_ids.filtered(lambda l: l.x).write({"product_uom_qty": 2})\n',
    ) == [("write", "2")]


def test_a_tree_with_no_python_is_refused(tmp_path):
    """Zero over an empty tree is the number a clean tree reports."""
    (tmp_path / "addons").mkdir()
    with pytest.raises(RuntimeError, match="refusing to report a count"):
        olq.measure([tmp_path / "addons"])
