import { describe, expect, test } from "@odoo/hoot";
import { waitFor } from "@odoo/hoot-dom";
import {
    contains,
    defineActions,
    defineModels,
    getService,
    mountWithCleanup,
} from "@web/../tests/web_test_helpers";
import { WebClient } from "@web/webclient/webclient";

import { DocumentsModels } from "@document/../tests/helpers/data";
import { makeDocumentsMockEnv } from "@document/../tests/helpers/model";
import { embeddedActionsServerData } from "@document/../tests/helpers/test_server_data";
import { basicDocumentsKanbanArch } from "@document/../tests/helpers/views/kanban";
import { basicDocumentsListArch } from "@document/../tests/helpers/views/list";
import { getEnrichedSearchArch } from "@document/../tests/helpers/views/search";

defineModels(DocumentsModels);
defineActions([
    {
        id: 1,
        name: "Documents",
        res_model: "document.document",
        views: [
            [false, "kanban"],
            [false, "list"],
        ],
    },
]);

describe.current.tags("desktop");

test("Keep showing actions on view switch", async function () {
    DocumentsModels.DocumentsDocument._views = {
        kanban: basicDocumentsKanbanArch,
        list: basicDocumentsListArch,
        [["search", false]]: getEnrichedSearchArch(),
    };
    await makeDocumentsMockEnv({ serverData: embeddedActionsServerData });
    await mountWithCleanup(WebClient);
    await getService("action").doAction(1);

    expect(`.o_kanban_view .o_content.o_component_with_search_panel`).toHaveCount(1);
    await contains(`.o_kanban_record:contains('Request 1')`).click();
    await waitFor(".o_control_panel_actions:contains('Action 1')");

    await getService("action").switchView("list");
    await waitFor(".o_data_row:contains('Request 1')");
    await waitFor(".o_control_panel_actions:contains('Action 1')");

    await getService("action").switchView("kanban");
    await waitFor(".o_kanban_record:contains('Request 1')");
    await waitFor(".o_control_panel_actions:contains('Action 1')");
});
