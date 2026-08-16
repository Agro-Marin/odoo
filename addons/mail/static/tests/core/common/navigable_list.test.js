import {
    click,
    contains,
    defineMailModels,
    start,
} from "@mail/../tests/mail_test_helpers";
import { NavigableList } from "@mail/core/common/navigable_list";
import { describe, test } from "@odoo/hoot";
import { press } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

test("escape dismisses a closeOnSelect=false navigable list", async () => {
    await start();
    await mountWithCleanup(NavigableList, {
        props: {
            anchorRef: document.body,
            closeOnSelect: false,
            onSelect: () => {},
            options: [{ label: "first option" }, { label: "second option" }],
        },
    });
    await contains(".o-mail-NavigableList-item", { count: 2 });
    await click(".o-mail-NavigableList-item:eq(0)");
    await contains(".o-mail-NavigableList-item", { count: 2 });
    await press("Escape");
    await contains(".o-mail-NavigableList-item", { count: 0 });
});
