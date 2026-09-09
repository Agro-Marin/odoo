import { describe, expect, test } from "@odoo/hoot";
import {
    defineModels,
    fields,
    getService,
    makeMockEnv,
    models,
} from "@web/../tests/web_test_helpers";
import "./hierarchy_mock_server.js";

/**
 * What the real `Base.hierarchy_read` answers, captured from a live database
 * (`res.partner`, ids renumbered 1..n, `order="id asc"`). The mock in
 * `hierarchy_mock_server.js` stands in for that method in every other suite in
 * this module, so a mock that answers a different question makes those suites
 * agree with nothing. Regenerate by re-running the probe against a scratch db.
 */
const CONTRACT = [
    {
        name: "lone root",
        records: [
            {
                id: 1,
                name: "n01",
                parent_id: false,
            },
        ],
        runs: [
            {
                domainIds: [1],
                expected: [
                    {
                        id: 1,
                        parent: false,
                        childIds: [],
                    },
                ],
            },
        ],
    },
    {
        name: "root with 2 children",
        records: [
            {
                id: 1,
                name: "n01",
                parent_id: false,
            },
            {
                id: 2,
                name: "n02",
                parent_id: 1,
            },
            {
                id: 3,
                name: "n03",
                parent_id: 1,
            },
        ],
        runs: [
            {
                domainIds: [1],
                expected: [
                    {
                        id: 1,
                        parent: false,
                        childIds: [],
                    },
                    {
                        id: 2,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 3,
                        parent: 1,
                        childIds: [],
                    },
                ],
            },
            {
                domainIds: [2],
                expected: [
                    {
                        id: 2,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 1,
                        parent: false,
                        childIds: [],
                    },
                    {
                        id: 3,
                        parent: 1,
                        childIds: [],
                    },
                ],
            },
            {
                domainIds: [1, 2],
                expected: [
                    {
                        id: 1,
                        parent: false,
                        childIds: [2, 3],
                    },
                    {
                        id: 2,
                        parent: 1,
                        childIds: [],
                    },
                ],
            },
            {
                domainIds: [1, 2, 3],
                expected: [
                    {
                        id: 1,
                        parent: false,
                        childIds: [2, 3],
                    },
                    {
                        id: 2,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 3,
                        parent: 1,
                        childIds: [],
                    },
                ],
            },
        ],
    },
    {
        name: "three levels",
        records: [
            {
                id: 1,
                name: "n01",
                parent_id: false,
            },
            {
                id: 2,
                name: "n02",
                parent_id: 1,
            },
            {
                id: 3,
                name: "n03",
                parent_id: 2,
            },
            {
                id: 4,
                name: "n04",
                parent_id: 3,
            },
        ],
        runs: [
            {
                domainIds: [1],
                expected: [
                    {
                        id: 1,
                        parent: false,
                        childIds: [],
                    },
                    {
                        id: 2,
                        parent: 1,
                        childIds: [3],
                    },
                ],
            },
            {
                domainIds: [2],
                expected: [
                    {
                        id: 2,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 1,
                        parent: false,
                        childIds: [],
                    },
                    {
                        id: 3,
                        parent: 2,
                        childIds: [4],
                    },
                ],
            },
            {
                domainIds: [3],
                expected: [
                    {
                        id: 3,
                        parent: 2,
                        childIds: [],
                    },
                    {
                        id: 2,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 4,
                        parent: 3,
                        childIds: [],
                    },
                ],
            },
            {
                domainIds: [4],
                expected: [
                    {
                        id: 4,
                        parent: 3,
                        childIds: [],
                    },
                    {
                        id: 3,
                        parent: 2,
                        childIds: [],
                    },
                ],
            },
            {
                domainIds: [1, 3],
                expected: [
                    {
                        id: 1,
                        parent: false,
                        childIds: [2],
                    },
                    {
                        id: 3,
                        parent: 2,
                        childIds: [4],
                    },
                ],
            },
        ],
    },
    {
        name: "two roots",
        records: [
            {
                id: 1,
                name: "n01",
                parent_id: false,
            },
            {
                id: 2,
                name: "n02",
                parent_id: false,
            },
            {
                id: 3,
                name: "n03",
                parent_id: 1,
            },
            {
                id: 4,
                name: "n04",
                parent_id: 2,
            },
        ],
        runs: [
            {
                domainIds: [1, 2],
                expected: [
                    {
                        id: 1,
                        parent: false,
                        childIds: [3],
                    },
                    {
                        id: 2,
                        parent: false,
                        childIds: [4],
                    },
                ],
            },
            {
                domainIds: [3],
                expected: [
                    {
                        id: 3,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 1,
                        parent: false,
                        childIds: [],
                    },
                ],
            },
            {
                domainIds: [1, 2, 3, 4],
                expected: [
                    {
                        id: 1,
                        parent: false,
                        childIds: [3],
                    },
                    {
                        id: 2,
                        parent: false,
                        childIds: [4],
                    },
                    {
                        id: 3,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 4,
                        parent: 2,
                        childIds: [],
                    },
                ],
            },
        ],
    },
    {
        name: "wide",
        records: [
            {
                id: 1,
                name: "n01",
                parent_id: false,
            },
            {
                id: 2,
                name: "n02",
                parent_id: 1,
            },
            {
                id: 3,
                name: "n03",
                parent_id: 1,
            },
            {
                id: 4,
                name: "n04",
                parent_id: 1,
            },
            {
                id: 5,
                name: "n05",
                parent_id: 1,
            },
        ],
        runs: [
            {
                domainIds: [1],
                expected: [
                    {
                        id: 1,
                        parent: false,
                        childIds: [],
                    },
                    {
                        id: 2,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 3,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 4,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 5,
                        parent: 1,
                        childIds: [],
                    },
                ],
            },
            {
                domainIds: [2],
                expected: [
                    {
                        id: 2,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 1,
                        parent: false,
                        childIds: [],
                    },
                    {
                        id: 3,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 4,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 5,
                        parent: 1,
                        childIds: [],
                    },
                ],
            },
            {
                domainIds: [1, 2, 3],
                expected: [
                    {
                        id: 1,
                        parent: false,
                        childIds: [2, 3, 4, 5],
                    },
                    {
                        id: 2,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 3,
                        parent: 1,
                        childIds: [],
                    },
                ],
            },
        ],
    },
    {
        name: "sibling with kids",
        records: [
            {
                id: 1,
                name: "n01",
                parent_id: false,
            },
            {
                id: 2,
                name: "n02",
                parent_id: 1,
            },
            {
                id: 3,
                name: "n03",
                parent_id: 1,
            },
            {
                id: 4,
                name: "n04",
                parent_id: 2,
            },
            {
                id: 5,
                name: "n05",
                parent_id: 3,
            },
        ],
        runs: [
            {
                domainIds: [2],
                expected: [
                    {
                        id: 2,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 1,
                        parent: false,
                        childIds: [],
                    },
                    {
                        id: 3,
                        parent: 1,
                        childIds: [5],
                    },
                    {
                        id: 4,
                        parent: 2,
                        childIds: [],
                    },
                ],
            },
            {
                domainIds: [3],
                expected: [
                    {
                        id: 3,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 1,
                        parent: false,
                        childIds: [],
                    },
                    {
                        id: 2,
                        parent: 1,
                        childIds: [4],
                    },
                    {
                        id: 5,
                        parent: 3,
                        childIds: [],
                    },
                ],
            },
            {
                domainIds: [1],
                expected: [
                    {
                        id: 1,
                        parent: false,
                        childIds: [],
                    },
                    {
                        id: 2,
                        parent: 1,
                        childIds: [4],
                    },
                    {
                        id: 3,
                        parent: 1,
                        childIds: [5],
                    },
                ],
            },
            {
                domainIds: [1, 2],
                expected: [
                    {
                        id: 1,
                        parent: false,
                        childIds: [2, 3],
                    },
                    {
                        id: 2,
                        parent: 1,
                        childIds: [4],
                    },
                ],
            },
        ],
    },
    {
        name: "deep from the middle",
        records: [
            {
                id: 1,
                name: "n01",
                parent_id: false,
            },
            {
                id: 2,
                name: "n02",
                parent_id: 1,
            },
            {
                id: 3,
                name: "n03",
                parent_id: 2,
            },
            {
                id: 4,
                name: "n04",
                parent_id: 3,
            },
            {
                id: 5,
                name: "n05",
                parent_id: 3,
            },
            {
                id: 6,
                name: "n06",
                parent_id: 1,
            },
        ],
        runs: [
            {
                domainIds: [3],
                expected: [
                    {
                        id: 3,
                        parent: 2,
                        childIds: [],
                    },
                    {
                        id: 2,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 4,
                        parent: 3,
                        childIds: [],
                    },
                    {
                        id: 5,
                        parent: 3,
                        childIds: [],
                    },
                ],
            },
            {
                domainIds: [2],
                expected: [
                    {
                        id: 2,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 1,
                        parent: false,
                        childIds: [],
                    },
                    {
                        id: 3,
                        parent: 2,
                        childIds: [4, 5],
                    },
                    {
                        id: 6,
                        parent: 1,
                        childIds: [],
                    },
                ],
            },
            {
                domainIds: [1, 4],
                expected: [
                    {
                        id: 1,
                        parent: false,
                        childIds: [2, 6],
                    },
                    {
                        id: 4,
                        parent: 3,
                        childIds: [],
                    },
                ],
            },
        ],
    },
    {
        name: "orphan parented",
        records: [
            {
                id: 1,
                name: "n01",
                parent_id: false,
            },
            {
                id: 2,
                name: "n02",
                parent_id: 1,
            },
            {
                id: 3,
                name: "n03",
                parent_id: 1,
            },
        ],
        runs: [
            {
                domainIds: [2, 3],
                expected: [
                    {
                        id: 2,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 3,
                        parent: 1,
                        childIds: [],
                    },
                ],
            },
        ],
    },
    {
        name: "grandchild only",
        records: [
            {
                id: 1,
                name: "n01",
                parent_id: false,
            },
            {
                id: 2,
                name: "n02",
                parent_id: 1,
            },
            {
                id: 3,
                name: "n03",
                parent_id: 2,
            },
            {
                id: 4,
                name: "n04",
                parent_id: 2,
            },
        ],
        runs: [
            {
                domainIds: [3],
                expected: [
                    {
                        id: 3,
                        parent: 2,
                        childIds: [],
                    },
                    {
                        id: 2,
                        parent: 1,
                        childIds: [],
                    },
                    {
                        id: 4,
                        parent: 2,
                        childIds: [],
                    },
                ],
            },
        ],
    },
];

class Employee extends models.Model {
    _name = "hr.employee";

    name = fields.Char();
    parent_id = fields.Many2one({ string: "Manager", relation: "hr.employee" });
    child_ids = fields.One2many({
        string: "Subordinates",
        relation: "hr.employee",
        relation_field: "parent_id",
    });
}

defineModels([Employee]);

describe.current.tags("headless");

function normalize(records) {
    return records.map((record) => ({
        id: record.id,
        parent: record.parent_id ? record.parent_id.id : false,
        childIds: [...(record.__child_ids__ || [])].sort((a, b) => a - b),
    }));
}

for (const fixture of CONTRACT) {
    test(`hierarchy_read contract: ${fixture.name}`, async () => {
        Employee._records = fixture.records;
        await makeMockEnv();
        for (const run of fixture.runs) {
            const result = await getService("orm").call(
                "hr.employee",
                "hierarchy_read",
                [
                    [["id", "in", run.domainIds]],
                    { name: {} },
                    "parent_id",
                    undefined,
                    "id asc",
                ],
                { context: {} },
            );
            expect(normalize(result)).toEqual(run.expected, {
                message: `${fixture.name} / domain ids ${JSON.stringify(run.domainIds)}`,
            });
        }
    });
}
