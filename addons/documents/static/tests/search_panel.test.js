import { describe, expect, test } from "@odoo/hoot";

import { DocumentsSearchPanel } from "@documents/views/search/documents_search_panel";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { _resetMediaQueryLists } from "@web/ui/viewport";

describe.current.tags("desktop");

/**
 * A panel reduced to what `_expandFolder` touches: the folder section's id, the
 * `expanded` state it writes, and the search model's two folder lookups.
 */
function makePanel(folders) {
    const values = new Map(folders.map((folder) => [folder.id, folder]));
    const panel = Object.create(DocumentsSearchPanel.prototype);
    Object.defineProperty(panel, "sections", { value: [{ id: 1 }] });
    panel.state = { expanded: { 1: {} } };
    panel.renderCount = 0;
    panel.render = () => (panel.renderCount += 1);
    panel.env = {
        searchModel: {
            getFolderById: (id) => values.get(id) || false,
            getFolderAndParents(folder) {
                const chain = [];
                while (folder) {
                    chain.push(folder);
                    folder = values.get(folder.folder_id || folder.user_folder_id);
                }
                return chain;
            },
        },
    };
    return panel;
}

const COMPANY_TREE = [
    { id: "COMPANY", rootId: "COMPANY" },
    { id: 1, folder_id: "COMPANY", rootId: "COMPANY" },
    { id: 2, folder_id: 1, rootId: "COMPANY" },
];

describe("_expandFolder", () => {
    test("unfolds the whole chain up to an expanded root", () => {
        const panel = makePanel(COMPANY_TREE);
        // The root is what `onWillStart` expands before asking for a folder.
        panel.state.expanded[1].COMPANY = true;
        panel._expandFolder({ folderId: 2 });
        expect(panel.state.expanded[1]).toEqual({ COMPANY: true, 1: true, 2: true });
        expect(panel.renderCount).toBe(1);
    });

    test("does nothing when the chain's root is still folded", () => {
        const panel = makePanel(COMPANY_TREE);
        panel._expandFolder({ folderId: 2 });
        expect(panel.state.expanded[1]).toEqual({});
        expect(panel.renderCount).toBe(0);
    });

    test("an id the panel does not hold is a no-op, not a crash", () => {
        // `getFolderById` answers `false` for an unknown id and
        // `getFolderAndParents(false)` is `[]`, which the ancestor test used to
        // dereference. `jumpToTarget` reaches here with a target whose
        // `user_folder_id` the panel never received.
        const panel = makePanel(COMPANY_TREE);
        panel.state.expanded[1].COMPANY = true;
        let thrown = null;
        try {
            panel._expandFolder({ folderId: 987654 });
        } catch (error) {
            thrown = error;
        }
        expect(thrown).toBe(null);
        expect(panel.state.expanded[1]).toEqual({ COMPANY: true });
        expect(panel.renderCount).toBe(0);
    });
});

test("template and subTemplates follow the viewport instead of freezing at import", () => {
    /** @param {number} width */
    const atWidth = (width) =>
        patchWithCleanup(browser, {
            matchMedia: (/** @type {string} */ query) => {
                const min = Number(/min-width:\s*(\d+)/.exec(query)?.[1] ?? 0);
                return /** @type {any} */ ({
                    matches: width >= min,
                    addEventListener() {},
                    removeEventListener() {},
                });
            },
        });

    atWidth(1400);
    _resetMediaQueryLists();
    expect(DocumentsSearchPanel.template).toBe("documents.SearchPanel");
    expect(DocumentsSearchPanel.subTemplates.category).toBe(
        "documents.SearchPanel.Category",
    );

    // the same class, asked again after the viewport moved
    atWidth(400);
    _resetMediaQueryLists();
    expect(DocumentsSearchPanel.template).toBe("documents.SearchPanel.Small");
    expect(DocumentsSearchPanel.subTemplates.category).toBe(
        "documents.SearchPanel.Category.Small",
    );
});
