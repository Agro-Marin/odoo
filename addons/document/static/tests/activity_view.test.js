import { describe, expect, test } from "@odoo/hoot";
import { mountView } from "@web/../tests/web_test_helpers";

import { defineDocumentsModels } from "@document/../tests/document_test_helpers";
import { getEnrichedSearchArch } from "@document/../tests/helpers/views/search";

describe.current.tags("desktop");
defineDocumentsModels();

test("the documents activity view mounts without a drag-and-drop wiring of its own", async () => {
    await mountView({
        type: "activity",
        resModel: "document.document",
        arch: `
            <activity string="Documents" js_class="documents_activity">
                <field name="folder_id"/>
                <templates>
                    <div t-name="activity-box">
                        <field name="name"/>
                    </div>
                </templates>
            </activity>`,
        searchViewArch: getEnrichedSearchArch(),
    });
    expect(".o_activity_view .o_activity_view_table").toHaveCount(1);
});
