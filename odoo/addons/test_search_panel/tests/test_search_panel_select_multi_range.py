import json

import odoo.tests
from odoo.exceptions import UserError

from .common import SEARCH_PANEL_ERROR, strip_version


@odoo.tests.tagged("post_install", "-at_install")
class TestSelectRangeMulti(odoo.tests.TransactionCase):
    def setUp(self):
        super().setUp()
        self.SourceModel = self.env["test_search_panel.source_model"]
        self.TargetModel = self.env["test_search_panel.filter_target_model"]
        self.GroupByModel = self.env["test_search_panel.category_target_model"]

    def _select_multi_range(self, *args, **kwargs):
        result = self.SourceModel.search_panel_select_multi_range(*args, **kwargs)
        return strip_version(result)

    def test_many2one_empty(self):
        result = self._select_multi_range("tag_id")
        self.assertEqual(
            result["values"],
            [],
        )

    def test_many2one(self):

        folders = self.GroupByModel.create(
            [
                {
                    "name": "Folder 1",
                },
                {
                    "name": "Folder 2",
                },
            ]
        )

        f1_id, f2_id = folders.ids

        tags = self.TargetModel.create(
            [
                {
                    "name": "Tag 1",
                    "folder_id": f2_id,
                    "color": "Red",
                    "status": "cool",
                },
                {
                    "name": "Tag 2",
                    "folder_id": f1_id,
                    "status": "cool",
                },
                {
                    "name": "Tag 3",
                    "color": "Green",
                    "status": "cool",
                },
            ]
        )

        t1_id, t2_id, t3_id = tags.ids

        records = self.SourceModel.create(
            [
                {
                    "name": "Rec 1",
                    "tag_id": t1_id,
                },
                {
                    "name": "Rec 2",
                    "tag_id": t1_id,
                },
                {
                    "name": "Rec 3",
                    "tag_id": t2_id,
                },
                {
                    "name": "Rec 4",
                },
            ]
        )

        r1_id, r2_id, _, _ = records.ids

        result = self._select_multi_range(
            "tag_id", enable_counters=True, expand=True, group_by="folder_id"
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "__count": 2,
                    "display_name": "Tag 1",
                    "id": t1_id,
                    "group_id": f2_id,
                    "group_name": "Folder 2",
                },
                {
                    "__count": 1,
                    "display_name": "Tag 2",
                    "id": t2_id,
                    "group_id": f1_id,
                    "group_name": "Folder 1",
                },
                {
                    "__count": 0,
                    "display_name": "Tag 3",
                    "id": t3_id,
                    "group_id": False,
                    "group_name": "Not Set",
                },
            ],
        )

        result = self._select_multi_range(
            "tag_id", enable_counters=True, expand=True, group_by="status"
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "__count": 2,
                    "display_name": "Tag 1",
                    "id": t1_id,
                    "group_id": "cool",
                    "group_name": "Cool",
                },
                {
                    "__count": 1,
                    "display_name": "Tag 2",
                    "id": t2_id,
                    "group_id": "cool",
                    "group_name": "Cool",
                },
                {
                    "__count": 0,
                    "display_name": "Tag 3",
                    "id": t3_id,
                    "group_id": "cool",
                    "group_name": "Cool",
                },
            ],
        )

        result = self._select_multi_range(
            "tag_id", enable_counters=True, expand=True, group_by="color"
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "__count": 2,
                    "display_name": "Tag 1",
                    "id": t1_id,
                    "group_id": "Red",
                    "group_name": "Red",
                },
                {
                    "__count": 1,
                    "display_name": "Tag 2",
                    "id": t2_id,
                    "group_id": False,
                    "group_name": "Not Set",
                },
                {
                    "__count": 0,
                    "display_name": "Tag 3",
                    "id": t3_id,
                    "group_id": "Green",
                    "group_name": "Green",
                },
            ],
        )

        result = self._select_multi_range(
            "tag_id",
            enable_counters=True,
            expand=True,
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "__count": 2,
                    "display_name": "Tag 1",
                    "id": t1_id,
                },
                {
                    "__count": 1,
                    "display_name": "Tag 2",
                    "id": t2_id,
                },
                {
                    "__count": 0,
                    "display_name": "Tag 3",
                    "id": t3_id,
                },
            ],
        )

        result = self._select_multi_range(
            "tag_id",
            enable_counters=True,
            expand=True,
            search_domain=[["id", "in", [r1_id, r2_id]]],
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "__count": 2,
                    "display_name": "Tag 1",
                    "id": t1_id,
                },
                {
                    "__count": 0,
                    "display_name": "Tag 2",
                    "id": t2_id,
                },
                {
                    "__count": 0,
                    "display_name": "Tag 3",
                    "id": t3_id,
                },
            ],
        )

        result = self._select_multi_range(
            "tag_id",
            enable_counters=True,
            expand=True,
            limit=2,
        )
        self.assertEqual(
            result,
            SEARCH_PANEL_ERROR,
        )

        result = self._select_multi_range(
            "tag_id",
            expand=True,
            group_by="folder_id",
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "display_name": "Tag 1",
                    "id": t1_id,
                    "group_id": f2_id,
                    "group_name": "Folder 2",
                },
                {
                    "display_name": "Tag 2",
                    "id": t2_id,
                    "group_id": f1_id,
                    "group_name": "Folder 1",
                },
                {
                    "display_name": "Tag 3",
                    "id": t3_id,
                    "group_id": False,
                    "group_name": "Not Set",
                },
            ],
        )

        result = self._select_multi_range(
            "tag_id",
            expand=True,
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "display_name": "Tag 1",
                    "id": t1_id,
                },
                {
                    "display_name": "Tag 2",
                    "id": t2_id,
                },
                {
                    "display_name": "Tag 3",
                    "id": t3_id,
                },
            ],
        )

        result = self._select_multi_range(
            "tag_id",
            expand=True,
            search_domain=[["id", "in", [r1_id, r2_id]]],
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "display_name": "Tag 1",
                    "id": t1_id,
                },
                {
                    "display_name": "Tag 2",
                    "id": t2_id,
                },
                {
                    "display_name": "Tag 3",
                    "id": t3_id,
                },
            ],
        )

        result = self._select_multi_range(
            "tag_id",
            enable_counters=True,
            group_by="folder_id",
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "__count": 2,
                    "display_name": "Tag 1",
                    "id": t1_id,
                    "group_id": f2_id,
                    "group_name": "Folder 2",
                },
                {
                    "__count": 1,
                    "display_name": "Tag 2",
                    "id": t2_id,
                    "group_id": f1_id,
                    "group_name": "Folder 1",
                },
            ],
        )

        result = self._select_multi_range(
            "tag_id",
            enable_counters=True,
            search_domain=[["id", "in", [r1_id, r2_id]]],
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "__count": 2,
                    "display_name": "Tag 1",
                    "id": t1_id,
                },
            ],
        )

        result = self._select_multi_range(
            "tag_id",
            enable_counters=True,
            limit=2,
        )
        self.assertEqual(
            result,
            SEARCH_PANEL_ERROR,
        )

        result = self._select_multi_range(
            "tag_id",
            group_by="folder_id",
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "display_name": "Tag 1",
                    "id": t1_id,
                    "group_id": f2_id,
                    "group_name": "Folder 2",
                },
                {
                    "display_name": "Tag 2",
                    "id": t2_id,
                    "group_id": f1_id,
                    "group_name": "Folder 1",
                },
            ],
        )

        result = self._select_multi_range(
            "tag_id",
            search_domain=[["id", "in", [r1_id, r2_id]]],
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "display_name": "Tag 1",
                    "id": t1_id,
                },
            ],
        )

        result = self._select_multi_range(
            "tag_id",
            comodel_domain=[["id", "in", [t2_id, t3_id]]],
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "display_name": "Tag 2",
                    "id": t2_id,
                },
            ],
        )

    def test_many2many_empty(self):
        result = self._select_multi_range("tag_ids")
        self.assertEqual(
            result["values"],
            [],
        )

    def test_many2many(self):

        folders = self.GroupByModel.create(
            [
                {
                    "name": "Folder 1",
                },
                {
                    "name": "Folder 2",
                },
            ]
        )

        f1_id, f2_id = folders.ids

        tags = self.TargetModel.create(
            [
                {
                    "name": "Tag 1",
                    "folder_id": f2_id,
                    "color": "Red",
                    "status": "cool",
                },
                {
                    "name": "Tag 2",
                    "folder_id": f1_id,
                    "status": "cool",
                },
                {
                    "name": "Tag 3",
                    "color": "Green",
                    "status": "cool",
                },
            ]
        )

        t1_id, t2_id, t3_id = tags.ids

        records = self.SourceModel.create(
            [
                {
                    "name": "Rec 1",
                    "tag_ids": [t1_id, t2_id, t3_id],
                },
                {
                    "name": "Rec 2",
                    "tag_ids": [t1_id],
                },
                {
                    "name": "Rec 3",
                    "tag_ids": [t2_id, t3_id],
                },
                {
                    "name": "Rec 4",
                },
            ]
        )

        r1_id, r2_id, _, _ = records.ids

        result = self._select_multi_range(
            "tag_ids", enable_counters=True, expand=True, group_by="folder_id"
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "__count": 2,
                    "display_name": "Tag 1",
                    "id": t1_id,
                    "group_id": f2_id,
                    "group_name": "Folder 2",
                },
                {
                    "__count": 2,
                    "display_name": "Tag 2",
                    "id": t2_id,
                    "group_id": f1_id,
                    "group_name": "Folder 1",
                },
                {
                    "__count": 2,
                    "display_name": "Tag 3",
                    "id": t3_id,
                    "group_id": False,
                    "group_name": "Not Set",
                },
            ],
        )

        result = self._select_multi_range(
            "tag_ids", enable_counters=True, expand=True, group_by="status"
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "__count": 2,
                    "display_name": "Tag 1",
                    "id": t1_id,
                    "group_id": "cool",
                    "group_name": "Cool",
                },
                {
                    "__count": 2,
                    "display_name": "Tag 2",
                    "id": t2_id,
                    "group_id": "cool",
                    "group_name": "Cool",
                },
                {
                    "__count": 2,
                    "display_name": "Tag 3",
                    "id": t3_id,
                    "group_id": "cool",
                    "group_name": "Cool",
                },
            ],
        )

        result = self._select_multi_range(
            "tag_ids", enable_counters=True, expand=True, group_by="color"
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "__count": 2,
                    "display_name": "Tag 1",
                    "id": t1_id,
                    "group_id": "Red",
                    "group_name": "Red",
                },
                {
                    "__count": 2,
                    "display_name": "Tag 2",
                    "id": t2_id,
                    "group_id": False,
                    "group_name": "Not Set",
                },
                {
                    "__count": 2,
                    "display_name": "Tag 3",
                    "id": t3_id,
                    "group_id": "Green",
                    "group_name": "Green",
                },
            ],
        )

        result = self._select_multi_range(
            "tag_ids",
            enable_counters=True,
            expand=True,
            group_by="folder_id",
            group_domain={
                json.dumps(f1_id): [
                    ("tag_ids", "in", [t1_id]),
                ],
                json.dumps(f2_id): [
                    ("tag_ids", "in", [t2_id]),
                ],
                json.dumps(False): [
                    ("tag_ids", "in", [t1_id]),
                    ("tag_ids", "in", [t2_id]),
                ],
            },
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "__count": 1,
                    "display_name": "Tag 1",
                    "id": t1_id,
                    "group_id": f2_id,
                    "group_name": "Folder 2",
                },
                {
                    "__count": 1,
                    "display_name": "Tag 2",
                    "id": t2_id,
                    "group_id": f1_id,
                    "group_name": "Folder 1",
                },
                {
                    "__count": 1,
                    "display_name": "Tag 3",
                    "id": t3_id,
                    "group_id": False,
                    "group_name": "Not Set",
                },
            ],
        )

        result = self._select_multi_range(
            "tag_ids",
            enable_counters=True,
            expand=True,
            group_by="color",
            group_domain={
                json.dumps(False): [
                    ("tag_ids", "in", [t1_id]),
                ],
                json.dumps("Green"): [
                    ("tag_ids", "in", [t1_id]),
                ],
            },
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "__count": 2,
                    "display_name": "Tag 1",
                    "id": t1_id,
                    "group_id": "Red",
                    "group_name": "Red",
                },
                {
                    "__count": 1,
                    "display_name": "Tag 2",
                    "id": t2_id,
                    "group_id": False,
                    "group_name": "Not Set",
                },
                {
                    "__count": 1,
                    "display_name": "Tag 3",
                    "id": t3_id,
                    "group_id": "Green",
                    "group_name": "Green",
                },
            ],
        )

        result = self._select_multi_range(
            "tag_ids",
            enable_counters=True,
            expand=True,
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "__count": 2,
                    "display_name": "Tag 1",
                    "id": t1_id,
                },
                {
                    "__count": 2,
                    "display_name": "Tag 2",
                    "id": t2_id,
                },
                {
                    "__count": 2,
                    "display_name": "Tag 3",
                    "id": t3_id,
                },
            ],
        )

        result = self._select_multi_range(
            "tag_ids",
            enable_counters=True,
            expand=True,
            search_domain=[["id", "in", [r1_id, r2_id]]],
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "__count": 2,
                    "display_name": "Tag 1",
                    "id": t1_id,
                },
                {
                    "__count": 1,
                    "display_name": "Tag 2",
                    "id": t2_id,
                },
                {
                    "__count": 1,
                    "display_name": "Tag 3",
                    "id": t3_id,
                },
            ],
        )

        result = self._select_multi_range(
            "tag_ids",
            expand=True,
            group_by="folder_id",
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "display_name": "Tag 1",
                    "id": t1_id,
                    "group_id": f2_id,
                    "group_name": "Folder 2",
                },
                {
                    "display_name": "Tag 2",
                    "id": t2_id,
                    "group_id": f1_id,
                    "group_name": "Folder 1",
                },
                {
                    "display_name": "Tag 3",
                    "id": t3_id,
                    "group_id": False,
                    "group_name": "Not Set",
                },
            ],
        )

        result = self._select_multi_range(
            "tag_ids",
            expand=True,
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "display_name": "Tag 1",
                    "id": t1_id,
                },
                {
                    "display_name": "Tag 2",
                    "id": t2_id,
                },
                {
                    "display_name": "Tag 3",
                    "id": t3_id,
                },
            ],
        )

        result = self._select_multi_range(
            "tag_ids",
            expand=True,
            search_domain=[["id", "in", [r1_id, r2_id]]],
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "display_name": "Tag 1",
                    "id": t1_id,
                },
                {
                    "display_name": "Tag 2",
                    "id": t2_id,
                },
                {
                    "display_name": "Tag 3",
                    "id": t3_id,
                },
            ],
        )

        result = self._select_multi_range(
            "tag_ids",
            enable_counters=True,
            group_by="folder_id",
            search_domain=[["id", "=", r2_id]],
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "__count": 1,
                    "display_name": "Tag 1",
                    "id": t1_id,
                    "group_id": f2_id,
                    "group_name": "Folder 2",
                },
            ],
        )

        result = self._select_multi_range(
            "tag_ids",
            enable_counters=True,
            search_domain=[["id", "=", r2_id]],
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "__count": 1,
                    "display_name": "Tag 1",
                    "id": t1_id,
                },
            ],
        )

        result = self._select_multi_range(
            "tag_ids",
            enable_counters=True,
            category_domain=[["id", "=", r2_id]],
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "__count": 1,
                    "display_name": "Tag 1",
                    "id": t1_id,
                },
                {
                    "__count": 0,
                    "display_name": "Tag 2",
                    "id": t2_id,
                },
                {
                    "__count": 0,
                    "display_name": "Tag 3",
                    "id": t3_id,
                },
            ],
        )

        result = self._select_multi_range(
            "tag_ids",
            group_by="folder_id",
            search_domain=[["id", "=", r2_id]],
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "display_name": "Tag 1",
                    "id": t1_id,
                    "group_id": f2_id,
                    "group_name": "Folder 2",
                },
            ],
        )

        result = self._select_multi_range(
            "tag_ids",
            search_domain=[["id", "=", r2_id]],
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "display_name": "Tag 1",
                    "id": t1_id,
                },
            ],
        )

        result = self._select_multi_range(
            "tag_ids",
            limit=2,
        )
        self.assertEqual(result, SEARCH_PANEL_ERROR)

        records = self.SourceModel.create(
            [
                {"name": "Rec 5", "tag_ids": [t2_id, t3_id]},
                {"name": "Rec 6", "tag_ids": [t3_id]},
            ]
        )
        r5_id, r6_id = records.ids

        result = self._select_multi_range(
            "tag_ids",
            search_domain=[["id", "=", r5_id]],
            limit=2,
        )
        self.assertEqual(result, SEARCH_PANEL_ERROR)

        result = self._select_multi_range(
            "tag_ids",
            search_domain=[["id", "=", r6_id]],
            limit=2,
        )
        self.assertEqual(
            result["values"],
            [
                {"display_name": "Tag 3", "id": t3_id},
            ],
        )

    def test_selection_empty(self):
        result = self._select_multi_range(
            "state",
            expand=True,
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "display_name": "A",
                    "id": "a",
                },
                {
                    "display_name": "B",
                    "id": "b",
                },
            ],
        )

    def test_selection(self):
        records = self.SourceModel.create(
            [
                {
                    "name": "Rec 1",
                    "state": "a",
                },
                {
                    "name": "Rec 2",
                    "state": "a",
                },
            ]
        )

        r1_id, _ = records.ids

        result = self._select_multi_range(
            "state",
            enable_counters=True,
            expand=True,
            group_by="not_possible_to_group",
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "display_name": "A",
                    "id": "a",
                    "__count": 2,
                },
                {
                    "display_name": "B",
                    "id": "b",
                    "__count": 0,
                },
            ],
        )

        result = self._select_multi_range(
            "state",
            enable_counters=True,
            expand=True,
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "display_name": "A",
                    "id": "a",
                    "__count": 2,
                },
                {
                    "display_name": "B",
                    "id": "b",
                    "__count": 0,
                },
            ],
        )

        result = self._select_multi_range(
            "state",
            enable_counters=True,
            expand=True,
            search_domain=[["id", "=", r1_id]],
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "display_name": "A",
                    "id": "a",
                    "__count": 1,
                },
                {
                    "display_name": "B",
                    "id": "b",
                    "__count": 0,
                },
            ],
        )

        result = self._select_multi_range(
            "state",
            expand=True,
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "display_name": "A",
                    "id": "a",
                },
                {
                    "display_name": "B",
                    "id": "b",
                },
            ],
        )

        result = self._select_multi_range(
            "state",
            expand=True,
            search_domain=[["id", "=", r1_id]],
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "display_name": "A",
                    "id": "a",
                },
                {
                    "display_name": "B",
                    "id": "b",
                },
            ],
        )

        result = self._select_multi_range(
            "state",
            enable_counters=True,
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "__count": 2,
                    "display_name": "A",
                    "id": "a",
                },
            ],
        )

        result = self._select_multi_range(
            "state",
        )
        self.assertEqual(
            result["values"],
            [
                {
                    "display_name": "A",
                    "id": "a",
                },
            ],
        )

    def test_unknown_field_raises_user_error(self):
        with self.assertRaises(UserError):
            self._select_multi_range("no_such_field")

    def test_unsupported_type_raises_user_error(self):
        with self.assertRaises(UserError):
            self._select_multi_range("name")
