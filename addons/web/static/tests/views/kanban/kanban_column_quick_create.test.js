// @ts-check

import { expect, getFixture, test } from "@odoo/hoot";
import { click, queryOne } from "@odoo/hoot-dom";
import { animationFrame, Deferred } from "@odoo/hoot-mock";
import { Component, onWillStart, xml } from "@odoo/owl";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { KanbanColumnQuickCreate } from "@web/views/kanban/kanban_column_quick_create";

class Blocker extends Component {
    static template = xml`<span class="o_blocker"/>`;
    static props = { started: Deferred, pending: Promise };

    setup() {
        onWillStart(() => {
            this.props.started.resolve();
            return this.props.pending;
        });
    }
}

class Host extends Component {
    static template = xml`
        <KanbanColumnQuickCreate
            folded="false"
            groupByField="{ string: 'Stage' }"
            onFoldChange="this.onFoldChange"
            onValidate="() => {}"
        />
        <Blocker started="this.props.started" pending="this.props.pending"/>`;
    static components = { Blocker, KanbanColumnQuickCreate };
    static props = { started: Deferred, pending: Promise };

    onFoldChange(/** @type {boolean} */ folded) {
        expect.step(`fold:${folded}`);
    }
}

async function setUpUnmountedQuickCreate() {
    const outside = document.createElement("button");
    outside.className = "o_outside";
    getFixture().append(outside);
    const started = new Deferred();
    const pending = new Deferred();
    mountWithCleanup(Host, { props: { started, pending } });
    await started;
    await animationFrame();
    expect(".o_column_quick_create").toHaveCount(0);
    return {
        async mount() {
            pending.resolve();
            await animationFrame();
            expect(".o_column_quick_create").toHaveCount(1);
        },
    };
}

test("a click landing between set up and mount neither throws nor folds", async () => {
    const quickCreate = await setUpUnmountedQuickCreate();

    await click(".o_outside");
    expect.verifySteps([]);

    await quickCreate.mount();
    await click(".o_column_quick_create input");
    expect.verifySteps([]);

    await click(".o_outside");
    expect.verifySteps(["fold:true"]);
});

test("a mousedown before mount does not decide where a later click started", async () => {
    const quickCreate = await setUpUnmountedQuickCreate();
    queryOne(".o_outside").dispatchEvent(
        new MouseEvent("mousedown", { bubbles: true }),
    );

    await quickCreate.mount();
    queryOne(".o_column_quick_create input").dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
    );
    expect.verifySteps([]);
});
