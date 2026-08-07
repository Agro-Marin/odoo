from odoo.tests import common


class TestFillTemporal(common.TransactionCase):
    maxDiff = None

    def setUp(self):
        super().setUp()
        self.Model = self.env["test_read_group.fill_temporal"]

    def test_date_range_and_flag(self):
        self.Model.create({"date": "1916-08-18", "value": 2})
        self.Model.create({"date": "1916-10-19", "value": 3})
        self.Model.create({"date": "1916-12-19", "value": 5})

        expected = [
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-08-01"),
                    ("date", "<", "1916-09-01"),
                ],
                "date:month": ("1916-08-01", "August 1916"),
                "__count": 1,
                "value:sum": 2,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-09-01"),
                    ("date", "<", "1916-10-01"),
                ],
                "date:month": ("1916-09-01", "September 1916"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-10-01"),
                    ("date", "<", "1916-11-01"),
                ],
                "date:month": ("1916-10-01", "October 1916"),
                "__count": 1,
                "value:sum": 3,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-11-01"),
                    ("date", "<", "1916-12-01"),
                ],
                "date:month": ("1916-11-01", "November 1916"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-12-01"),
                    ("date", "<", "1917-01-01"),
                ],
                "date:month": ("1916-12-01", "December 1916"),
                "__count": 1,
                "value:sum": 5,
            },
        ]

        groups = self.Model.formatted_read_group(
            [], groupby=["date:month"], aggregates=["__count", "value:sum"]
        )

        self.assertEqual(groups, [group for group in expected if group["__count"]])

        groups = self.Model.with_context(fill_temporal=True).formatted_read_group(
            [],
            groupby=["date:month"],
            aggregates=["__count", "value:sum"],
        )

        self.assertEqual(groups, expected)

        Model = self.Model.with_context(fill_temporal=True)
        self.assertEqual(
            Model.formatted_read_grouping_sets(
                [], [["date:month"], []], ["__count", "value:sum"]
            ),
            [
                Model.formatted_read_group(
                    [], ["date:month"], ["__count", "value:sum"]
                ),
                Model.formatted_read_group([], [], ["__count", "value:sum"]),
            ],
        )

    def test_date_range_with_context_timezone(self):
        self.Model.create({"date": "1915-01-01", "value": 3})
        self.Model.create({"date": "1916-01-01", "value": 5})

        expected = [
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1915-01-01"),
                    ("date", "<", "1915-02-01"),
                ],
                "date:month": ("1915-01-01", "January 1915"),
                "__count": 1,
                "value:sum": 3,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1915-02-01"),
                    ("date", "<", "1915-03-01"),
                ],
                "date:month": ("1915-02-01", "February 1915"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1915-03-01"),
                    ("date", "<", "1915-04-01"),
                ],
                "date:month": ("1915-03-01", "March 1915"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1915-04-01"),
                    ("date", "<", "1915-05-01"),
                ],
                "date:month": ("1915-04-01", "April 1915"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1915-05-01"),
                    ("date", "<", "1915-06-01"),
                ],
                "date:month": ("1915-05-01", "May 1915"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1915-06-01"),
                    ("date", "<", "1915-07-01"),
                ],
                "date:month": ("1915-06-01", "June 1915"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1915-07-01"),
                    ("date", "<", "1915-08-01"),
                ],
                "date:month": ("1915-07-01", "July 1915"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1915-08-01"),
                    ("date", "<", "1915-09-01"),
                ],
                "date:month": ("1915-08-01", "August 1915"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1915-09-01"),
                    ("date", "<", "1915-10-01"),
                ],
                "date:month": ("1915-09-01", "September 1915"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1915-10-01"),
                    ("date", "<", "1915-11-01"),
                ],
                "date:month": ("1915-10-01", "October 1915"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1915-11-01"),
                    ("date", "<", "1915-12-01"),
                ],
                "date:month": ("1915-11-01", "November 1915"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1915-12-01"),
                    ("date", "<", "1916-01-01"),
                ],
                "date:month": ("1915-12-01", "December 1915"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-01-01"),
                    ("date", "<", "1916-02-01"),
                ],
                "date:month": ("1916-01-01", "January 1916"),
                "__count": 1,
                "value:sum": 5,
            },
        ]

        tzs = [
            "America/Anchorage",
            "Europe/Brussels",
            "Pacific/Kwajalein",
        ]

        for tz in tzs:
            model = self.Model.with_context(tz=tz, fill_temporal=True)
            groups = model.formatted_read_group(
                [], groupby=["date:month"], aggregates=["__count", "value:sum"]
            )
            self.assertEqual(groups, expected)

    def test_only_with_only_null_date(self):
        self.Model.create({"date": False, "value": 13})
        self.Model.create({"date": False, "value": 11})
        self.Model.create({"date": False, "value": 17})

        expected = [
            {
                "__extra_domain": [("date", "=", False)],
                "__count": 3,
                "value:sum": 41,
                "date:month": False,
            }
        ]

        groups = self.Model.formatted_read_group(
            [], groupby=["date:month"], aggregates=["__count", "value:sum"]
        )
        self.assertEqual(groups, expected)

        groups = self.Model.with_context(fill_temporal=True).formatted_read_group(
            [], groupby=["date:month"], aggregates=["__count", "value:sum"]
        )
        self.assertEqual(groups, expected)

    def test_date_range_and_null_date(self):
        self.Model.create({"date": "1916-08-19", "value": 4})
        self.Model.create({"date": False, "value": 13})
        self.Model.create({"date": "1916-10-18", "value": 5})
        self.Model.create({"date": "1916-08-18", "value": 3})
        self.Model.create({"date": "1916-10-19", "value": 4})
        self.Model.create({"date": False, "value": 11})

        expected = [
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-08-01"),
                    ("date", "<", "1916-09-01"),
                ],
                "date:month": ("1916-08-01", "August 1916"),
                "__count": 2,
                "value:sum": 7,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-09-01"),
                    ("date", "<", "1916-10-01"),
                ],
                "date:month": ("1916-09-01", "September 1916"),
                "__count": 0,
                "value:sum": 0,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-10-01"),
                    ("date", "<", "1916-11-01"),
                ],
                "date:month": ("1916-10-01", "October 1916"),
                "__count": 2,
                "value:sum": 9,
            },
            {
                "__extra_domain": [("date", "=", False)],
                "date:month": False,
                "__count": 2,
                "value:sum": 24,
            },
        ]

        groups = self.Model.formatted_read_group(
            [], groupby=["date:month"], aggregates=["__count", "value:sum"]
        )
        self.assertEqual(groups, [group for group in expected if group["__count"]])

        groups = self.Model.with_context(fill_temporal=True).formatted_read_group(
            [], groupby=["date:month"], aggregates=["__count", "value:sum"]
        )
        self.assertEqual(groups, expected)

    def test_multiple_groupby(self):
        self.Model.create(
            [
                {"date": "1916-08-19", "value": 1},
                {"date": "1916-08-20", "value": 2},
                {"date": "1916-12-14", "value": 1},
                {"date": "1916-12-14", "value": 1},
                {"date": False, "value": 1},
                {"date": False, "value": 2},
            ]
        )

        expected = [
            {
                "date:month": ("1916-08-01", "August 1916"),
                "value": 1,
                "__extra_domain": [
                    "&",
                    "&",
                    ("date", ">=", "1916-08-01"),
                    ("date", "<", "1916-09-01"),
                    ("value", "=", 1),
                ],
                "__count": 1,
            },
            {
                "date:month": ("1916-08-01", "August 1916"),
                "value": 2,
                "__extra_domain": [
                    "&",
                    "&",
                    ("date", ">=", "1916-08-01"),
                    ("date", "<", "1916-09-01"),
                    ("value", "=", 2),
                ],
                "__count": 1,
            },
            {
                "date:month": ("1916-09-01", "September 1916"),
                "value": False,
                "__count": 0,
                "__extra_domain": [
                    "&",
                    "&",
                    ("date", ">=", "1916-09-01"),
                    ("date", "<", "1916-10-01"),
                    ("value", "=", False),
                ],
            },
            {
                "date:month": ("1916-10-01", "October 1916"),
                "value": False,
                "__count": 0,
                "__extra_domain": [
                    "&",
                    "&",
                    ("date", ">=", "1916-10-01"),
                    ("date", "<", "1916-11-01"),
                    ("value", "=", False),
                ],
            },
            {
                "date:month": ("1916-11-01", "November 1916"),
                "value": False,
                "__count": 0,
                "__extra_domain": [
                    "&",
                    "&",
                    ("date", ">=", "1916-11-01"),
                    ("date", "<", "1916-12-01"),
                    ("value", "=", False),
                ],
            },
            {
                "date:month": ("1916-12-01", "December 1916"),
                "value": 1,
                "__extra_domain": [
                    "&",
                    "&",
                    ("date", ">=", "1916-12-01"),
                    ("date", "<", "1917-01-01"),
                    ("value", "=", 1),
                ],
                "__count": 2,
            },
            {
                "date:month": False,
                "value": 1,
                "__extra_domain": [
                    "&",
                    ("date", "=", False),
                    ("value", "=", 1),
                ],
                "__count": 1,
            },
            {
                "date:month": False,
                "value": 2,
                "__extra_domain": [
                    "&",
                    ("date", "=", False),
                    ("value", "=", 2),
                ],
                "__count": 1,
            },
        ]

        groups = self.Model.with_context(fill_temporal=True).formatted_read_group(
            [], groupby=["date:month", "value"], aggregates=["__count"]
        )
        self.assertEqual(groups, expected)

    def test_date_range_groupby_week(self):
        self.Model.create(
            [
                {"date": "1916-08-19", "value": 4},
                {"date": "1916-08-20", "value": 13},
                {"date": "1916-09-10", "value": 5},
                {"date": "1916-08-18", "value": 3},
                {"date": "1916-09-11", "value": 4},
                {"date": "1916-09-12", "value": 11},
            ]
        )

        expected = [
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-08-13"),
                    ("date", "<", "1916-08-20"),
                ],
                "date:week": ("1916-08-13", "W34 1916"),
                "__count": 2,
                "value:sum": 7,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-08-20"),
                    ("date", "<", "1916-08-27"),
                ],
                "date:week": ("1916-08-20", "W35 1916"),
                "__count": 1,
                "value:sum": 13,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-08-27"),
                    ("date", "<", "1916-09-03"),
                ],
                "date:week": ("1916-08-27", "W36 1916"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-09-03"),
                    ("date", "<", "1916-09-10"),
                ],
                "date:week": ("1916-09-03", "W37 1916"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-09-10"),
                    ("date", "<", "1916-09-17"),
                ],
                "date:week": ("1916-09-10", "W38 1916"),
                "__count": 3,
                "value:sum": 20,
            },
        ]

        groups = self.Model.formatted_read_group(
            [], ["date:week"], ["__count", "value:sum"]
        )

        self.assertEqual(groups, [group for group in expected if group["__count"]])

        groups = self.Model.with_context(fill_temporal=True).formatted_read_group(
            [], ["date:week"], ["__count", "value:sum"]
        )

        self.assertEqual(groups, expected)

    def test_order_date_desc(self):
        self.Model.create({"date": "1916-08-18", "value": 3})
        self.Model.create({"date": "1916-08-19", "value": 4})
        self.Model.create({"date": "1916-10-18", "value": 5})
        self.Model.create({"date": "1916-10-19", "value": 4})
        self.patch(self.registry[self.Model._name], "_order", "date desc")

        expected = [
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-08-01"),
                    ("date", "<", "1916-09-01"),
                ],
                "date:month": ("1916-08-01", "August 1916"),
                "__count": 2,
                "value:sum": 7,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-09-01"),
                    ("date", "<", "1916-10-01"),
                ],
                "date:month": ("1916-09-01", "September 1916"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-10-01"),
                    ("date", "<", "1916-11-01"),
                ],
                "date:month": ("1916-10-01", "October 1916"),
                "__count": 2,
                "value:sum": 9,
            },
        ]

        groups = self.Model.formatted_read_group(
            [], ["date:month"], ["__count", "value:sum"]
        )
        self.assertEqual(groups, [group for group in expected if group["__count"]])

        groups = self.Model.with_context(fill_temporal=True).formatted_read_group(
            [], ["date:month"], ["__count", "value:sum"]
        )
        self.assertEqual(groups, expected)

    def test_timestamp_without_timezone(self):
        self.Model.create({"datetime": "1916-08-19 01:30:00", "value": 7})
        self.Model.create({"datetime": False, "value": 13})
        self.Model.create({"datetime": "1916-10-18 02:30:00", "value": 5})
        self.Model.create({"datetime": "1916-08-18 01:50:00", "value": 3})
        self.Model.create({"datetime": False, "value": 11})
        self.Model.create({"datetime": "1916-10-19 23:59:59", "value": 2})
        self.Model.create({"datetime": "1916-10-19", "value": 19})

        expected = [
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-08-01 00:00:00"),
                    ("datetime", "<", "1916-09-01 00:00:00"),
                ],
                "datetime:month": ("1916-08-01 00:00:00", "August 1916"),
                "__count": 2,
                "value:sum": 10,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-09-01 00:00:00"),
                    ("datetime", "<", "1916-10-01 00:00:00"),
                ],
                "datetime:month": ("1916-09-01 00:00:00", "September 1916"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-10-01 00:00:00"),
                    ("datetime", "<", "1916-11-01 00:00:00"),
                ],
                "datetime:month": ("1916-10-01 00:00:00", "October 1916"),
                "__count": 3,
                "value:sum": 26,
            },
            {
                "__extra_domain": [("datetime", "=", False)],
                "datetime:month": False,
                "__count": 2,
                "value:sum": 24,
            },
        ]

        groups = self.Model.formatted_read_group(
            [], ["datetime:month"], ["__count", "value:sum"]
        )
        self.assertEqual(groups, [group for group in expected if group["__count"]])

        groups = self.Model.with_context(fill_temporal=True).formatted_read_group(
            [], ["datetime:month"], ["__count", "value:sum"]
        )
        self.assertEqual(groups, expected)

    def test_with_datetimes_and_groupby_per_hour(self):
        self.Model.create({"datetime": "1916-01-01 01:30:00", "value": 2})
        self.Model.create({"datetime": "1916-01-01 01:50:00", "value": 8})
        self.Model.create({"datetime": "1916-01-01 02:30:00", "value": 3})
        self.Model.create({"datetime": "1916-01-01 13:50:00", "value": 5})
        self.Model.create({"datetime": "1916-01-01 23:50:00", "value": 7})

        expected = [
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 01:00:00"),
                    ("datetime", "<", "1916-01-01 02:00:00"),
                ],
                "datetime:hour": ("1916-01-01 01:00:00", "01:00 01 Jan"),
                "__count": 2,
                "value:sum": 10,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 02:00:00"),
                    ("datetime", "<", "1916-01-01 03:00:00"),
                ],
                "datetime:hour": ("1916-01-01 02:00:00", "02:00 01 Jan"),
                "__count": 1,
                "value:sum": 3,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 03:00:00"),
                    ("datetime", "<", "1916-01-01 04:00:00"),
                ],
                "datetime:hour": ("1916-01-01 03:00:00", "03:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 04:00:00"),
                    ("datetime", "<", "1916-01-01 05:00:00"),
                ],
                "datetime:hour": ("1916-01-01 04:00:00", "04:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 05:00:00"),
                    ("datetime", "<", "1916-01-01 06:00:00"),
                ],
                "datetime:hour": ("1916-01-01 05:00:00", "05:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 06:00:00"),
                    ("datetime", "<", "1916-01-01 07:00:00"),
                ],
                "datetime:hour": ("1916-01-01 06:00:00", "06:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 07:00:00"),
                    ("datetime", "<", "1916-01-01 08:00:00"),
                ],
                "datetime:hour": ("1916-01-01 07:00:00", "07:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 08:00:00"),
                    ("datetime", "<", "1916-01-01 09:00:00"),
                ],
                "datetime:hour": ("1916-01-01 08:00:00", "08:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 09:00:00"),
                    ("datetime", "<", "1916-01-01 10:00:00"),
                ],
                "datetime:hour": ("1916-01-01 09:00:00", "09:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 10:00:00"),
                    ("datetime", "<", "1916-01-01 11:00:00"),
                ],
                "datetime:hour": ("1916-01-01 10:00:00", "10:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 11:00:00"),
                    ("datetime", "<", "1916-01-01 12:00:00"),
                ],
                "datetime:hour": ("1916-01-01 11:00:00", "11:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 12:00:00"),
                    ("datetime", "<", "1916-01-01 13:00:00"),
                ],
                "datetime:hour": ("1916-01-01 12:00:00", "12:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 13:00:00"),
                    ("datetime", "<", "1916-01-01 14:00:00"),
                ],
                "datetime:hour": ("1916-01-01 13:00:00", "01:00 01 Jan"),
                "__count": 1,
                "value:sum": 5,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 14:00:00"),
                    ("datetime", "<", "1916-01-01 15:00:00"),
                ],
                "datetime:hour": ("1916-01-01 14:00:00", "02:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 15:00:00"),
                    ("datetime", "<", "1916-01-01 16:00:00"),
                ],
                "datetime:hour": ("1916-01-01 15:00:00", "03:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 16:00:00"),
                    ("datetime", "<", "1916-01-01 17:00:00"),
                ],
                "datetime:hour": ("1916-01-01 16:00:00", "04:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 17:00:00"),
                    ("datetime", "<", "1916-01-01 18:00:00"),
                ],
                "datetime:hour": ("1916-01-01 17:00:00", "05:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 18:00:00"),
                    ("datetime", "<", "1916-01-01 19:00:00"),
                ],
                "datetime:hour": ("1916-01-01 18:00:00", "06:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 19:00:00"),
                    ("datetime", "<", "1916-01-01 20:00:00"),
                ],
                "datetime:hour": ("1916-01-01 19:00:00", "07:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 20:00:00"),
                    ("datetime", "<", "1916-01-01 21:00:00"),
                ],
                "datetime:hour": ("1916-01-01 20:00:00", "08:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 21:00:00"),
                    ("datetime", "<", "1916-01-01 22:00:00"),
                ],
                "datetime:hour": ("1916-01-01 21:00:00", "09:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 22:00:00"),
                    ("datetime", "<", "1916-01-01 23:00:00"),
                ],
                "datetime:hour": ("1916-01-01 22:00:00", "10:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 23:00:00"),
                    ("datetime", "<", "1916-01-02 00:00:00"),
                ],
                "datetime:hour": ("1916-01-01 23:00:00", "11:00 01 Jan"),
                "__count": 1,
                "value:sum": 7,
            },
        ]

        groups = self.Model.with_context(fill_temporal=True).formatted_read_group(
            [], ["datetime:hour"], ["__count", "value:sum"]
        )
        self.assertEqual(groups, expected)

    def test_hour_with_timezones(self):
        self.Model.create({"datetime": "1915-12-31 22:30:00", "value": 2})
        self.Model.create({"datetime": "1916-01-01 03:30:00", "value": 3})

        expected = [
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1915-12-31 22:00:00"),
                    ("datetime", "<", "1915-12-31 23:00:00"),
                ],
                "datetime:hour": ("1915-12-31 22:00:00", "04:00 01 Jan"),
                "__count": 1,
                "value:sum": 2,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1915-12-31 23:00:00"),
                    ("datetime", "<", "1916-01-01 00:00:00"),
                ],
                "datetime:hour": ("1915-12-31 23:00:00", "05:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 00:00:00"),
                    ("datetime", "<", "1916-01-01 01:00:00"),
                ],
                "datetime:hour": ("1916-01-01 00:00:00", "06:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 01:00:00"),
                    ("datetime", "<", "1916-01-01 02:00:00"),
                ],
                "datetime:hour": ("1916-01-01 01:00:00", "07:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 02:00:00"),
                    ("datetime", "<", "1916-01-01 03:00:00"),
                ],
                "datetime:hour": ("1916-01-01 02:00:00", "08:00 01 Jan"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "1916-01-01 03:00:00"),
                    ("datetime", "<", "1916-01-01 04:00:00"),
                ],
                "datetime:hour": ("1916-01-01 03:00:00", "09:00 01 Jan"),
                "__count": 1,
                "value:sum": 3,
            },
        ]

        model_fill = self.Model.with_context(tz="Asia/Hovd", fill_temporal=True)
        groups = model_fill.formatted_read_group(
            [], ["datetime:hour"], ["__count", "value:sum"]
        )
        self.assertEqual(groups, expected)

    def test_quarter_with_timezones(self):
        self.Model.create({"datetime": "2016-01-01 03:30:00", "value": 2})
        self.Model.create({"datetime": "2016-12-30 22:30:00", "value": 3})

        expected = [
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "2015-12-31 17:00:00"),
                    ("datetime", "<", "2016-03-31 16:00:00"),
                ],
                "datetime:quarter": ("2015-12-31 17:00:00", "Q1 2016"),
                "__count": 1,
                "value:sum": 2,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "2016-03-31 16:00:00"),
                    ("datetime", "<", "2016-06-30 16:00:00"),
                ],
                "datetime:quarter": ("2016-03-31 16:00:00", "Q2 2016"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "2016-06-30 16:00:00"),
                    ("datetime", "<", "2016-09-30 17:00:00"),
                ],
                "datetime:quarter": ("2016-06-30 16:00:00", "Q3 2016"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "2016-09-30 17:00:00"),
                    ("datetime", "<", "2016-12-31 17:00:00"),
                ],
                "datetime:quarter": ("2016-09-30 17:00:00", "Q4 2016"),
                "__count": 1,
                "value:sum": 3,
            },
        ]

        model_fill = self.Model.with_context(tz="Asia/Hovd", fill_temporal=True)
        groups = model_fill.formatted_read_group(
            [], ["datetime:quarter"], ["__count", "value:sum"]
        )
        self.assertEqual(groups, expected)

    def test_edge_fx_tz(self):
        self.Model.create({"datetime": "2017-12-31 21:00:00", "value": 42})

        expected = [
            {
                "__extra_domain": [
                    "&",
                    ("datetime", ">=", "2017-12-31 17:00:00"),
                    ("datetime", "<", "2018-01-31 17:00:00"),
                ],
                "datetime:month": ("2017-12-31 17:00:00", "January 2018"),
                "__count": 1,
                "value:sum": 42,
            }
        ]

        model_fill = self.Model.with_context(tz="Asia/Hovd", fill_temporal=True)
        groups = model_fill.formatted_read_group(
            [], ["datetime:month"], ["__count", "value:sum"]
        )
        self.assertEqual(groups, expected)

    def test_with_bounds(self):
        self.Model.create({"date": "1916-02-15", "value": 1})
        self.Model.create({"date": "1916-06-15", "value": 2})
        self.Model.create({"date": "1916-11-15", "value": 3})

        expected = [
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-02-01"),
                    ("date", "<", "1916-03-01"),
                ],
                "date:month": ("1916-02-01", "February 1916"),
                "__count": 1,
                "value:sum": 1,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-05-01"),
                    ("date", "<", "1916-06-01"),
                ],
                "date:month": ("1916-05-01", "May 1916"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-06-01"),
                    ("date", "<", "1916-07-01"),
                ],
                "date:month": ("1916-06-01", "June 1916"),
                "__count": 1,
                "value:sum": 2,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-07-01"),
                    ("date", "<", "1916-08-01"),
                ],
                "date:month": ("1916-07-01", "July 1916"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-08-01"),
                    ("date", "<", "1916-09-01"),
                ],
                "date:month": ("1916-08-01", "August 1916"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-11-01"),
                    ("date", "<", "1916-12-01"),
                ],
                "date:month": ("1916-11-01", "November 1916"),
                "__count": 1,
                "value:sum": 3,
            },
        ]

        groups = self.Model.with_context(
            fill_temporal={"fill_from": "1916-05-15", "fill_to": "1916-08-15"}
        ).formatted_read_group([], ["date:month"], ["__count", "value:sum"])
        self.assertEqual(groups, expected)

    def test_datetime_bounds_with_timezone(self):
        self.Model.create({"datetime": "1916-06-15 10:00:00", "value": 7})

        groups = self.Model.with_context(
            tz="Europe/Brussels",
            fill_temporal={
                "fill_from": "1916-02-15 05:30:00",
                "fill_to": "1916-04-15 23:00:00",
            },
        ).formatted_read_group([], ["datetime:month"], ["__count", "value:sum"])

        self.assertEqual(len(groups), 4)
        self.assertEqual(sum(g["value:sum"] or 0 for g in groups), 7)
        self.assertEqual([g["__count"] for g in groups], [0, 0, 0, 1])

    def test_with_bounds_groupby_week(self):
        self.Model.create(
            [
                {"date": "1916-08-19", "value": 4},
                {"date": "1916-08-20", "value": 13},
                {"date": "1916-09-10", "value": 5},
                {"date": "1916-08-18", "value": 3},
                {"date": "1916-09-11", "value": 4},
                {"date": "1916-09-12", "value": 11},
            ]
        )

        expected = [
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-08-06"),
                    ("date", "<", "1916-08-13"),
                ],
                "date:week": ("1916-08-06", "W33 1916"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-08-13"),
                    ("date", "<", "1916-08-20"),
                ],
                "date:week": ("1916-08-13", "W34 1916"),
                "__count": 2,
                "value:sum": 7,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-08-20"),
                    ("date", "<", "1916-08-27"),
                ],
                "date:week": ("1916-08-20", "W35 1916"),
                "__count": 1,
                "value:sum": 13,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-08-27"),
                    ("date", "<", "1916-09-03"),
                ],
                "date:week": ("1916-08-27", "W36 1916"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-09-03"),
                    ("date", "<", "1916-09-10"),
                ],
                "date:week": ("1916-09-03", "W37 1916"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-09-10"),
                    ("date", "<", "1916-09-17"),
                ],
                "date:week": ("1916-09-10", "W38 1916"),
                "__count": 3,
                "value:sum": 20,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-09-17"),
                    ("date", "<", "1916-09-24"),
                ],
                "date:week": ("1916-09-17", "W39 1916"),
                "__count": 0,
                "value:sum": False,
            },
        ]

        groups = self.Model.with_context(
            fill_temporal={"fill_from": "1916-08-10", "fill_to": "1916-09-20"}
        ).formatted_read_group(
            [],
            ["date:week"],
            ["__count", "value:sum"],
        )

        self.assertEqual(groups, expected)

    def test_upper_bound(self):
        self.Model.create({"date": "1916-02-15", "value": 1})

        expected = [
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-02-01"),
                    ("date", "<", "1916-03-01"),
                ],
                "date:month": ("1916-02-01", "February 1916"),
                "__count": 1,
                "value:sum": 1,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-03-01"),
                    ("date", "<", "1916-04-01"),
                ],
                "date:month": ("1916-03-01", "March 1916"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-04-01"),
                    ("date", "<", "1916-05-01"),
                ],
                "date:month": ("1916-04-01", "April 1916"),
                "__count": 0,
                "value:sum": False,
            },
        ]

        groups = self.Model.with_context(
            fill_temporal={"fill_to": "1916-04-15"}
        ).formatted_read_group(
            [],
            ["date:month"],
            ["__count", "value:sum"],
        )
        self.assertEqual(groups, expected)

    def test_lower_bound(self):
        self.Model.create({"date": "1916-04-15", "value": 1})

        expected = [
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-02-01"),
                    ("date", "<", "1916-03-01"),
                ],
                "date:month": ("1916-02-01", "February 1916"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-03-01"),
                    ("date", "<", "1916-04-01"),
                ],
                "date:month": ("1916-03-01", "March 1916"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-04-01"),
                    ("date", "<", "1916-05-01"),
                ],
                "date:month": ("1916-04-01", "April 1916"),
                "__count": 1,
                "value:sum": 1,
            },
        ]

        groups = self.Model.with_context(
            fill_temporal={"fill_from": "1916-02-15"}
        ).formatted_read_group(
            [],
            ["date:month"],
            ["__count", "value:sum"],
        )

        self.assertEqual(groups, expected)

    def test_empty_context_key(self):
        self.Model.create({"date": "1916-02-15", "value": 1})
        self.Model.create({"date": "1916-04-15", "value": 2})

        expected = [
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-02-01"),
                    ("date", "<", "1916-03-01"),
                ],
                "date:month": ("1916-02-01", "February 1916"),
                "__count": 1,
                "value:sum": 1,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-03-01"),
                    ("date", "<", "1916-04-01"),
                ],
                "date:month": ("1916-03-01", "March 1916"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-04-01"),
                    ("date", "<", "1916-05-01"),
                ],
                "date:month": ("1916-04-01", "April 1916"),
                "__count": 1,
                "value:sum": 2,
            },
        ]

        groups = self.Model.with_context(fill_temporal={}).formatted_read_group(
            [],
            groupby=["date:month"],
            aggregates=["__count", "value:sum"],
        )

        self.assertEqual(groups, expected)

    def test_min_groups(self):
        self.Model.create({"date": "1916-02-15", "value": 1})

        expected = [
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-02-01"),
                    ("date", "<", "1916-03-01"),
                ],
                "date:month": ("1916-02-01", "February 1916"),
                "__count": 1,
                "value:sum": 1,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-03-01"),
                    ("date", "<", "1916-04-01"),
                ],
                "date:month": ("1916-03-01", "March 1916"),
                "__count": 0,
                "value:sum": False,
            },
        ]

        groups = self.Model.with_context(
            fill_temporal={"min_groups": 2}
        ).formatted_read_group(
            [],
            ["date:month"],
            ["__count", "value:sum"],
        )
        self.assertEqual(groups, expected)

    def test_with_bounds_and_min_groups(self):
        self.Model.create({"date": "1916-02-15", "value": 1})
        self.Model.create({"date": "1916-06-15", "value": 2})
        self.Model.create({"date": "1916-11-15", "value": 3})

        expected = [
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-02-01"),
                    ("date", "<", "1916-03-01"),
                ],
                "date:month": ("1916-02-01", "February 1916"),
                "__count": 1,
                "value:sum": 1,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-05-01"),
                    ("date", "<", "1916-06-01"),
                ],
                "date:month": ("1916-05-01", "May 1916"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-06-01"),
                    ("date", "<", "1916-07-01"),
                ],
                "date:month": ("1916-06-01", "June 1916"),
                "__count": 1,
                "value:sum": 2,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-07-01"),
                    ("date", "<", "1916-08-01"),
                ],
                "date:month": ("1916-07-01", "July 1916"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-08-01"),
                    ("date", "<", "1916-09-01"),
                ],
                "date:month": ("1916-08-01", "August 1916"),
                "__count": 0,
                "value:sum": False,
            },
            {
                "__extra_domain": [
                    "&",
                    ("date", ">=", "1916-11-01"),
                    ("date", "<", "1916-12-01"),
                ],
                "date:month": ("1916-11-01", "November 1916"),
                "__count": 1,
                "value:sum": 3,
            },
        ]

        groups = self.Model.with_context(
            fill_temporal={
                "fill_from": "1916-05-15",
                "fill_to": "1916-07-15",
                "min_groups": 4,
            }
        ).formatted_read_group(
            [],
            ["date:month"],
            ["__count", "value:sum"],
        )
        self.assertEqual(groups, expected)
