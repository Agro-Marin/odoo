import { describe, expect, test } from "@odoo/hoot";
import { queryAll } from "@odoo/hoot-dom";
import { contains } from "@web/../tests/web_test_helpers";

import { defineDocumentsModels } from "@document/../tests/document_test_helpers";
import { getDocumentsTestServerModelsData } from "./helpers/data.js";
import { makeDocumentsMockEnv } from "./helpers/model.js";
import { mountDocumentsKanbanView } from "./helpers/views/kanban.js";

describe.current.tags("desktop");
defineDocumentsModels();

test("share, move and duplicate are hidden without document_enterprise", async () => {
    const serverData = getDocumentsTestServerModelsData();
    const { name: folder1Name } = serverData["document.document"][0];
    await makeDocumentsMockEnv({ serverData, enterpriseActions: false });
    await mountDocumentsKanbanView();
    await contains(
        `.o_kanban_record:contains(${folder1Name}) .o_record_selector`,
    ).click({
        ctrlKey: true,
    });
    expect("button:contains(Share)").toHaveCount(0);
    await contains(".o_cp_action_menus button").click();
    expect(queryAll(".o-dropdown--menu .o-dropdown-item").length).toBeGreaterThan(0);
    expect(".o-dropdown-item:contains(Move):not(:contains(Trash))").toHaveCount(0);
    expect(".o-dropdown-item:contains(Duplicate)").toHaveCount(0);
});
