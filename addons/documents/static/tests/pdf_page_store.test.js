import {
    makePdfPageStoreData,
    PdfPageStore,
} from "@documents/owl/components/pdf_manager/pdf_page_store";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("headless");

/**
 * @param {Object} [param0]
 * @param {number} [param0.pageCount]
 * @param {boolean} [param0.groupPerPage]
 * @param {Object} [param0.data]
 * @returns {PdfPageStore}
 */
function buildStore({ pageCount = 6, groupPerPage = true, data } = {}) {
    const store = new PdfPageStore(data);
    store.createPagesForFile({ fileId: "file1", name: "doc", pageCount, groupPerPage });
    return store;
}

function mergeAllGroups(store) {
    while (store.groupIds.length > 1) {
        const groupId = store.groupIds[0];
        const pageIds = store.getGroup(groupId).pageIds;
        store.toggleSeparator(pageIds[pageIds.length - 1], groupId);
    }
}

describe("isLastPageOfGroup", () => {
    test("only the closing page of a group reports true", () => {
        const store = buildStore({ pageCount: 4, groupPerPage: false });
        const [p1, p2, p3, p4] = store.sortedPageIds;

        expect(store.isLastPageOfGroup(p1)).toBe(false);
        expect(store.isLastPageOfGroup(p2)).toBe(false);
        expect(store.isLastPageOfGroup(p3)).toBe(false);
        expect(store.isLastPageOfGroup(p4)).toBe(true);
    });

    test("tracks the boundary as groups are split and merged", () => {
        const store = buildStore({ pageCount: 4, groupPerPage: false });
        const [p1, p2] = store.sortedPageIds;
        const groupId = store.groupIds[0];

        store.toggleSeparator(p2, groupId);
        expect(store.isLastPageOfGroup(p2)).toBe(true);
        expect(store.isLastPageOfGroup(p1)).toBe(false);

        store.toggleSeparator(p2, groupId);
        expect(store.isLastPageOfGroup(p2)).toBe(false);
        expect(() => store.checkInvariants()).not.toThrow();
    });

    test("one group per page makes every page a boundary", () => {
        const store = buildStore({ pageCount: 3 });
        for (const pageId of store.sortedPageIds) {
            expect(store.isLastPageOfGroup(pageId)).toBe(true);
        }
    });

    test("a detached or unknown page is not a boundary", () => {
        const store = buildStore({ pageCount: 2 });
        const [p1] = store.sortedPageIds;

        store.removePage(p1);
        expect(store.isLastPageOfGroup(p1)).toBe(false, {
            message: "a page with no group has no separator after it",
        });
        expect(store.isLastPageOfGroup("nope")).toBe(false);
    });
});

describe("a page belongs to at most one group", () => {
    test("attaching a page detaches it from its previous group", () => {
        const store = buildStore({ pageCount: 4 });
        const [p1, p2, p3, p4] = store.sortedPageIds;
        const [g1, g2] = store.groupIds;

        store.addPage(p1, g2);

        expect(store.getGroup(g2).pageIds).toEqual([p2, p1]);
        expect(store.getGroup(g1)).toBe(undefined, {
            message: "the group p1 left is gone: it held nothing else",
        });
        expect(store.getPage(p1).groupId).toBe(g2);
        expect(store.sortedPageIds).toEqual([p2, p1, p3, p4]);
        expect(store.numberOfPages).toBe(4);
        expect(() => store.checkInvariants()).not.toThrow();
    });

    test("adding the same page to the same group twice lists it once", () => {
        const store = buildStore({ pageCount: 3, groupPerPage: false });
        const [p1] = store.sortedPageIds;
        const [groupId] = store.groupIds;

        store.addPage(p1, groupId);
        store.addPage(p1, groupId);

        expect(store.getGroup(groupId).pageIds.filter((id) => id === p1)).toHaveLength(
            1,
        );
        expect(store.numberOfPages).toBe(3);
        expect(() => store.checkInvariants()).not.toThrow();
    });
});

describe("a group never lists a page that does not exist", () => {
    test("attaching an unknown page is refused", () => {
        const store = buildStore({ pageCount: 2, groupPerPage: false });
        const [groupId] = store.groupIds;

        expect(store.addPage("page_that_never_existed", groupId)).toBe(false);
        expect(store.getGroup(groupId).pageIds).toHaveLength(2);
        expect(store.numberOfPages).toBe(2);
        expect(() => store.checkInvariants()).not.toThrow();
    });

    test("attaching to an unknown group is refused and leaves the page put", () => {
        const store = buildStore({ pageCount: 2, groupPerPage: false });
        const [p1] = store.sortedPageIds;
        const [groupId] = store.groupIds;

        expect(store.addPage(p1, "group_that_never_existed")).toBe(false);
        expect(store.getPage(p1).groupId).toBe(groupId, {
            message: "a refused move must not detach the page",
        });
        expect(store.numberOfPages).toBe(2);
        expect(() => store.checkInvariants()).not.toThrow();
    });

    test("creating a group from unknown ids yields an empty, consistent group", () => {
        const store = buildStore({ pageCount: 2, groupPerPage: false });

        const groupId = store.createGroup({
            name: "ghosts",
            pageIds: ["nope", "nope2"],
        });

        expect(store.getGroup(groupId).pageIds).toEqual([]);
        expect(store.numberOfPages).toBe(2);
    });
});

describe("numberOfPages equals the number of grouped pages", () => {
    test("it tracks every kind of mutation", () => {
        const store = buildStore({ pageCount: 6 });
        expect(store.numberOfPages).toBe(6);

        const [p1, p2] = store.sortedPageIds;

        store.removePage(p1);
        expect(store.numberOfPages).toBe(5);
        expect(() => store.checkInvariants()).not.toThrow();

        store.addPage(p1, store.getPage(p2).groupId);
        expect(store.numberOfPages).toBe(6);
        expect(() => store.checkInvariants()).not.toThrow();

        store.deletePage(p1);
        expect(store.numberOfPages).toBe(5);
        expect(store.getPage(p1)).toBe(undefined);
        expect(() => store.checkInvariants()).not.toThrow();

        store.clearGroups();
        expect(store.numberOfPages).toBe(0);
        expect(store.groupIds).toEqual([]);
        expect(() => store.checkInvariants()).not.toThrow();

        store.createGroup({ name: "all", pageIds: Object.keys(store.pages) });
        expect(store.numberOfPages).toBe(5);
        expect(() => store.checkInvariants()).not.toThrow();
    });

    test("a reorder never changes it", () => {
        const store = buildStore({ pageCount: 6, groupPerPage: false });
        const [p1, , , p4] = store.sortedPageIds;

        store.movePage(p1, p4);
        store.movePage(p4, p1);

        expect(store.numberOfPages).toBe(6);
        expect(() => store.checkInvariants()).not.toThrow();
    });
});

describe("a group that loses its last page is removed", () => {
    test("removing the last page drops the group from groupIds and groupData", () => {
        const store = buildStore({ pageCount: 2 });
        const [p1] = store.sortedPageIds;
        const [g1, g2] = store.groupIds;

        store.removePage(p1);

        expect(store.groupIds).toEqual([g2]);
        expect(store.getGroup(g1)).toBe(undefined);
        expect(() => store.checkInvariants()).not.toThrow();
    });

    test("a non-empty group survives", () => {
        const store = buildStore({ pageCount: 3, groupPerPage: false });
        const [p1] = store.sortedPageIds;
        const [groupId] = store.groupIds;

        store.removePage(p1);

        expect(store.groupIds).toEqual([groupId]);
        expect(store.getGroup(groupId).pageIds).toHaveLength(2);
        expect(() => store.checkInvariants()).not.toThrow();
    });

    test("a same-group move does not let the group vanish in between", () => {
        const store = buildStore({ pageCount: 1 });
        const [p1] = store.sortedPageIds;
        const [groupId] = store.groupIds;

        expect(store.addPage(p1, groupId, { index: 0 })).toBe(true);
        expect(store.groupIds).toEqual([groupId]);
        expect(store.getGroup(groupId).pageIds).toEqual([p1]);
        expect(store.numberOfPages).toBe(1);
        expect(() => store.checkInvariants()).not.toThrow();
    });
});

describe("focus and last selection never reference a detached page", () => {
    test("removing the focused page releases the focus", () => {
        const store = buildStore({ pageCount: 3 });
        const [p1, p2] = store.sortedPageIds;
        store.focusedPage = p1;
        store.lastSelectedPage = p2;

        store.removePage(p1);
        expect(store.focusedPage).toBe(undefined);
        expect(store.lastSelectedPage).toBe(p2, {
            message: "other references are untouched",
        });

        store.deletePage(p2);
        expect(store.lastSelectedPage).toBe(undefined);
        expect(() => store.checkInvariants()).not.toThrow();
    });

    test("a reorder keeps the focus", () => {
        const store = buildStore({ pageCount: 6, groupPerPage: false });
        const [p1, , , p4] = store.sortedPageIds;
        store.focusedPage = p1;
        store.lastSelectedPage = p1;

        store.movePage(p1, p4);

        expect(store.focusedPage).toBe(p1);
        expect(store.lastSelectedPage).toBe(p1);
        expect(() => store.checkInvariants()).not.toThrow();
    });
});

describe("regression: createGroup over pages that are still in another group", () => {
    test("no page is duplicated and the counter stays exact", () => {
        const store = buildStore({ pageCount: 6, groupPerPage: false });
        const ignored = store.sortedPageIds.slice(0, 3);

        store.createGroup({
            name: "Remaining Pages",
            pageIds: ignored,
            isSelected: true,
        });

        const listed = store.sortedPageIds;
        expect(listed).toHaveLength(6, { message: "the 6 pages are each listed once" });
        expect(new Set(listed).size).toBe(6, {
            message: "no page id appears in two groups",
        });
        expect(store.numberOfPages).toBe(6);
        expect(() => store.checkInvariants()).not.toThrow();

        store.createGroup({
            name: "Remaining Pages",
            pageIds: ignored,
            isSelected: true,
        });

        expect(store.sortedPageIds).toHaveLength(6, {
            message: "retrying does not accumulate pages",
        });
        expect(store.numberOfPages).toBe(6);
        expect(() => store.checkInvariants()).not.toThrow();
    });

    test("re-adopting pages after a wholesale group reset stays consistent", () => {
        const store = buildStore({ pageCount: 6 });
        const allPageIds = store.sortedPageIds;

        store.clearGroups();
        store.createGroup({ name: "all", pageIds: allPageIds });

        expect(store.groupIds).toHaveLength(1);
        expect(store.sortedPageIds).toEqual(allPageIds);
        expect(store.numberOfPages).toBe(6);
        expect(() => store.checkInvariants()).not.toThrow();
    });
});

describe("regression: removing a page that has no group", () => {
    test("it does not throw", () => {
        const store = buildStore({ pageCount: 3 });
        const [p1] = store.sortedPageIds;

        store.removePage(p1);
        expect(store.getPage(p1).groupId).toBe(false);

        expect(() => store.removePage(p1)).not.toThrow();
        expect(store.numberOfPages).toBe(2, {
            message: "a second removal must not decrement the counter again",
        });
        expect(() => store.checkInvariants()).not.toThrow();
    });

    test("removing an unknown page is a no-op", () => {
        const store = buildStore({ pageCount: 3 });

        expect(store.removePage("never_existed")).toBe(false);
        expect(() => store.deletePage("never_existed")).not.toThrow();
        expect(store.numberOfPages).toBe(3);
        expect(() => store.checkInvariants()).not.toThrow();
    });
});

describe("regression: same-group drag lands on the target's index", () => {
    test("forward and backward drags are symmetric", () => {
        const store = buildStore({ pageCount: 6, groupPerPage: false });
        const [p1, p2, p3, p4, p5, p6] = store.sortedPageIds;

        store.movePage(p1, p4);
        expect(store.sortedPageIds).toEqual([p2, p3, p1, p4, p5, p6]);
        expect(() => store.checkInvariants()).not.toThrow();

        store.movePage(p1, p2);
        expect(store.sortedPageIds).toEqual([p1, p2, p3, p4, p5, p6]);
        expect(store.numberOfPages).toBe(6);
        expect(() => store.checkInvariants()).not.toThrow();
    });

    test("a cross-group drop lands on the target's index untouched", () => {
        const store = buildStore({ pageCount: 4, groupPerPage: false });
        const [p1, p2, p3, p4] = store.sortedPageIds;
        const otherGroupId = store.createGroup({ name: "other" });
        store.addPage(p4, otherGroupId);

        store.movePage(p4, p2);

        expect(store.getGroup(store.getPage(p1).groupId).pageIds).toEqual([
            p1,
            p4,
            p2,
            p3,
        ]);
        expect(store.numberOfPages).toBe(4);
        expect(() => store.checkInvariants()).not.toThrow();
    });
});

describe("regression: a large merge does not recompute the page count", () => {
    test("merging 400 single-page groups never walks every group", () => {
        class CountingStore extends PdfPageStore {
            sortedPageIdsReads = 0;
            get sortedPageIds() {
                this.sortedPageIdsReads++;
                return super.sortedPageIds;
            }
        }
        const store = buildStore({ pageCount: 400, data: makePdfPageStoreData() });
        const counting = new CountingStore(store.data);
        expect(counting.groupIds).toHaveLength(400);

        const started = performance.now();
        mergeAllGroups(counting);
        const elapsed = performance.now() - started;

        expect(counting.sortedPageIdsReads).toBe(0, {
            message: "no mutation on the merge path recomputes the page list",
        });
        expect(counting.groupIds).toHaveLength(1);
        expect(counting.getGroup(counting.groupIds[0]).pageIds).toHaveLength(400);
        expect(counting.numberOfPages).toBe(400);
        expect(() => counting.checkInvariants()).not.toThrow();
        expect(elapsed).toBeLessThan(500, {
            message: `merging 400 pages took ${Math.round(elapsed)}ms`,
        });
    });

    test("the counter stays exact through a full merge and re-split", () => {
        const store = buildStore({ pageCount: 40 });
        mergeAllGroups(store);
        expect(store.numberOfPages).toBe(40);
        expect(() => store.checkInvariants()).not.toThrow();

        const groupId = store.groupIds[0];
        for (const pageId of [...store.getGroup(groupId).pageIds].slice(0, -1)) {
            store.toggleSeparator(pageId, store.getPage(pageId).groupId);
        }
        expect(store.groupIds).toHaveLength(40);
        expect(store.numberOfPages).toBe(40);
        expect(() => store.checkInvariants()).not.toThrow();
    });
});

describe("group operations", () => {
    test("toggleSeparator splits a group in two and merges it back", () => {
        const store = buildStore({ pageCount: 6, groupPerPage: false });
        const [p1, p2, p3, p4, p5, p6] = store.sortedPageIds;
        const [groupId] = store.groupIds;

        store.toggleSeparator(p3, groupId);
        expect(store.groupIds).toHaveLength(2);
        expect(store.getGroup(store.groupIds[0]).pageIds).toEqual([p1, p2, p3]);
        expect(store.getGroup(store.groupIds[1]).pageIds).toEqual([p4, p5, p6]);
        expect(store.numberOfPages).toBe(6);
        expect(() => store.checkInvariants()).not.toThrow();

        store.toggleSeparator(p3, store.groupIds[0]);
        expect(store.groupIds).toHaveLength(1);
        expect(store.sortedPageIds).toEqual([p1, p2, p3, p4, p5, p6]);
        expect(store.numberOfPages).toBe(6);
        expect(() => store.checkInvariants()).not.toThrow();
    });

    test("toggleSeparator on the last page of the last group is a no-op", () => {
        const store = buildStore({ pageCount: 3, groupPerPage: false });
        const pageIds = store.sortedPageIds;
        const [groupId] = store.groupIds;

        store.toggleSeparator(pageIds[2], groupId);

        expect(store.groupIds).toEqual([groupId]);
        expect(store.sortedPageIds).toEqual(pageIds);
        expect(() => store.checkInvariants()).not.toThrow();
    });

    test("regroupAll gathers everything into one group", () => {
        const store = buildStore({ pageCount: 6 });
        const allPageIds = store.sortedPageIds;

        const groupId = store.regroupAll({ name: "Remaining Pages", isSelected: true });

        expect(store.groupIds).toEqual([groupId]);
        expect(store.getGroup(groupId).pageIds).toEqual(allPageIds);
        expect(store.getGroup(groupId).name).toBe("Remaining Pages");
        expect(store.selectedPageIds).toHaveLength(6);
        expect(store.numberOfPages).toBe(6);
        expect(() => store.checkInvariants()).not.toThrow();
    });

    test("splitOnBlankPages rebuilds the grouping without losing a page", () => {
        const store = buildStore({ pageCount: 6, groupPerPage: false });
        const allPageIds = store.sortedPageIds;
        store.getPage(allPageIds[2]).isBlank = true;
        store.getPage(allPageIds[3]).isBlank = true;

        store.splitOnBlankPages({
            blankName: "Blank Page",
            subDocName: (count) => `sub-doc-${count}`,
        });

        expect(store.groupIds).toHaveLength(3);
        expect(store.groupIds.map((id) => store.getGroup(id).name)).toEqual([
            "sub-doc-1",
            "Blank Page",
            "sub-doc-2",
        ]);
        expect(store.sortedPageIds).toEqual(allPageIds, {
            message: "neither loses nor duplicates nor reorders a page",
        });
        expect(store.numberOfPages).toBe(6);
        expect(store.selectedPageIds).toHaveLength(4, {
            message: "the blank pages are deselected",
        });
        expect(() => store.checkInvariants()).not.toThrow();
    });

    test("splitOnBlankPages leaves no empty group when the first page is blank", () => {
        const store = buildStore({ pageCount: 4, groupPerPage: false });
        const allPageIds = store.sortedPageIds;
        store.getPage(allPageIds[0]).isBlank = true;

        store.splitOnBlankPages({
            blankName: "Blank Page",
            subDocName: (count) => `sub-doc-${count}`,
        });

        expect(store.groupIds).toHaveLength(2);
        expect(store.sortedPageIds).toEqual(allPageIds);
        expect(() => store.checkInvariants()).not.toThrow();
    });

    test("splitOnBlankPages on an empty store is a no-op", () => {
        const store = new PdfPageStore();
        expect(() =>
            store.splitOnBlankPages({ blankName: "b", subDocName: (n) => `${n}` }),
        ).not.toThrow();
        expect(store.groupIds).toEqual([]);
    });

    test("createGroup honours an explicit index", () => {
        const store = buildStore({ pageCount: 2 });
        const [g1, g2] = store.groupIds;

        const inserted = store.createGroup({ name: "between", index: 1 });

        expect(store.groupIds).toEqual([g1, inserted, g2]);
    });

    test("renameGroup falls back to a placeholder on an empty name", () => {
        const store = buildStore({ pageCount: 1 });
        const [groupId] = store.groupIds;

        store.renameGroup(groupId, "");
        expect(store.getGroup(groupId).name).toBeOfType("string");
        expect(store.getGroup(groupId).name).not.toBe("");

        store.renameGroup(groupId, "named");
        expect(store.getGroup(groupId).name).toBe("named");

        expect(() => store.renameGroup("no_such_group", "x")).not.toThrow();
    });
});

describe("selection", () => {
    test("selected / ignored only ever cover grouped pages", () => {
        const store = buildStore({ pageCount: 4, groupPerPage: false });
        const [p1, p2, p3] = store.sortedPageIds;

        store.setSelected(p1, false);
        expect(store.selectedPageIds).toHaveLength(3);
        expect(store.ignoredPageIds).toEqual([p1]);
        expect(store.allSelected).toBe(false);

        store.removePage(p2);
        expect(store.selectedPageIds).not.toInclude(p2);
        expect(store.ignoredPageIds).not.toInclude(p2);

        store.selectAll(true);
        expect(store.allSelected).toBe(true);
        expect(store.selectedPageIds).toHaveLength(3, {
            message: "the detached page is selected but not listed",
        });

        store.toggleSelectAll();
        expect(store.selectedPageIds).toEqual([]);
        expect(store.ignoredPageIds).toHaveLength(3);

        store.setSelected(p3, true);
        store.unselectAll();
        expect(store.selectedPageIds).toEqual([]);
    });

    test("clickSelect extends the selection from the last clicked page", () => {
        const store = buildStore({ pageCount: 6, groupPerPage: false });
        const [p1, p2, p3, p4] = store.sortedPageIds;
        store.selectAll(false);

        store.clickSelect(p1);
        expect(store.lastSelectedPage).toBe(p1);
        expect(store.selectedPageIds).toEqual([p1]);

        store.clickSelect(p4, { isRangeSelection: true });
        expect(store.selectedPageIds).toEqual([p1, p2, p3, p4]);
        expect(store.lastSelectedPage).toBe(p4);

        store.clickSelect(p4, { isRangeSelection: true });
        expect(store.selectedPageIds).toEqual([p1, p2, p3]);
    });

    test("toggleGroupSelection selects a partial group and deselects a full one", () => {
        const store = buildStore({ pageCount: 6, groupPerPage: false });
        const [groupId] = store.groupIds;
        const [p1] = store.sortedPageIds;

        store.toggleGroupSelection(groupId);
        expect(store.selectedPageIds).toEqual([]);

        store.setSelected(p1, true);
        store.toggleGroupSelection(groupId);
        expect(store.selectedPageIds).toHaveLength(6);

        expect(() => store.toggleGroupSelection("no_such_group")).not.toThrow();
    });

    test("selectUntilSplit covers the focused page's side of its group", () => {
        const store = buildStore({ pageCount: 6, groupPerPage: false });
        const pageIds = store.sortedPageIds;
        store.selectAll(false);
        store.focusedPage = pageIds[2];

        store.selectUntilSplit("right");
        expect(store.selectedPageIds).toEqual(pageIds.slice(2));

        store.selectAll(false);
        store.selectUntilSplit("left");
        expect(store.selectedPageIds).toEqual(pageIds.slice(0, 3));
    });

    test("selectUntilSplit falls back to the last selection, then to the first page", () => {
        const store = buildStore({ pageCount: 4, groupPerPage: false });
        const pageIds = store.sortedPageIds;
        store.selectAll(false);

        store.selectUntilSplit("right");
        expect(store.focusedPage).toBe(pageIds[0], {
            message: "nothing focused nor selected: the focus lands on the first page",
        });

        store.focusedPage = undefined;
        store.lastSelectedPage = pageIds[2];
        store.selectUntilSplit("right");
        expect(store.focusedPage).toBe(pageIds[2]);
        expect(store.selectedPageIds).toEqual(pageIds.slice(2));
    });
});

describe("focus navigation", () => {
    test("the focus steps through the pages in display order", () => {
        const store = buildStore({ pageCount: 4, groupPerPage: false });
        const [p1, p2, p3] = store.sortedPageIds;

        store.focusNextPage("right", false);
        expect(store.focusedPage).toBe(p1, {
            message: "the first step takes the focus",
        });

        store.focusNextPage("right", false);
        expect(store.focusedPage).toBe(p2);

        store.focusNextPage("right", false);
        expect(store.focusedPage).toBe(p3);

        store.focusNextPage("left", false);
        expect(store.focusedPage).toBe(p2);
    });

    test("vertical steps use the caller's cards-per-line measurement", () => {
        const store = buildStore({ pageCount: 9, groupPerPage: false });
        const pageIds = store.sortedPageIds;
        store.focusedPage = pageIds[0];

        store.focusNextPage("down", false, () => 3);
        expect(store.focusedPage).toBe(pageIds[3]);

        store.focusNextPage("up", false, () => 3);
        expect(store.focusedPage).toBe(pageIds[0]);
    });

    test("stepping past the last page keeps the focus put", () => {
        const store = buildStore({ pageCount: 2, groupPerPage: false });
        const pageIds = store.sortedPageIds;
        store.focusedPage = pageIds[1];

        store.focusNextPage("right", false);
        expect(store.focusedPage).toBe(pageIds[1]);
    });

    test("navigating an empty store does not throw", () => {
        const store = new PdfPageStore();

        expect(() => store.focusNextPage("right", false)).not.toThrow();
        expect(() => store.focusNextPage("right", true)).not.toThrow();
        expect(() => store.focusNextGroup("right")).not.toThrow();
        expect(store.focusedPage).toBe(undefined);
    });

    test("focusNextGroup lands on the first page of the neighbouring group", () => {
        const store = buildStore({ pageCount: 6, groupPerPage: false });
        const pageIds = store.sortedPageIds;
        store.toggleSeparator(pageIds[2], store.groupIds[0]);
        store.focusedPage = pageIds[0];

        store.focusNextGroup("right");
        expect(store.focusedPage).toBe(pageIds[3]);

        store.focusNextGroup("right");
        expect(store.focusedPage).toBe(pageIds[3], {
            message: "no group after the last one",
        });

        store.focusNextGroup("left");
        expect(store.focusedPage).toBe(pageIds[0]);
    });
});

describe("checkInvariants", () => {
    test("it is not vacuous: every invariant it claims to guard is detected", () => {
        const corruptions = {
            "a page in two groups": (store) => {
                const [p1] = store.sortedPageIds;
                store.getGroup(store.groupIds[1]).pageIds.push(p1);
            },
            "an unknown page in a group": (store) => {
                store.getGroup(store.groupIds[0]).pageIds.push("ghost");
            },
            "a drifted counter": (store) => {
                store.data.numberOfPages += 1;
            },
            "an orphan group in groupIds": (store) => {
                store.data.groupIds.push("group_that_does_not_exist");
            },
            "a group missing from groupIds": (store) => {
                store.data.groupIds = store.data.groupIds.slice(1);
            },
            "a dangling focus": (store) => {
                store.data.focusedPage = "detached_page";
            },
            "a dangling last selection": (store) => {
                store.data.lastSelectedPage = "detached_page";
            },
            "a page pointing at a group that does not list it": (store) => {
                store.getPage(store.sortedPageIds[0]).groupId = store.groupIds[1];
            },
        };
        for (const [label, corrupt] of Object.entries(corruptions)) {
            const store = buildStore({ pageCount: 4 });
            expect(() => store.checkInvariants()).not.toThrow();
            corrupt(store);
            expect(() => store.checkInvariants()).toThrow(/invariants violated/, {
                message: `checkInvariants must catch ${label}`,
            });
        }
    });
});

describe("the store is reactivity-agnostic", () => {
    test("it works on any plain container handed to it", () => {
        const data = makePdfPageStoreData();
        const store = new PdfPageStore(data);
        store.createPagesForFile({ fileId: "f", name: "doc", pageCount: 3 });

        expect(store.data).toBe(data, {
            message: "the container is the caller's, untouched",
        });
        expect(Object.keys(data)).toEqual([
            "pages",
            "groupData",
            "groupIds",
            "numberOfPages",
            "focusedPage",
            "lastSelectedPage",
        ]);
        expect(store.numberOfPages).toBe(3);

        expect(() => JSON.stringify(data)).not.toThrow();
        expect(JSON.parse(JSON.stringify(data)).numberOfPages).toBe(3);
    });

    test("two stores can share one container", () => {
        const data = makePdfPageStoreData();
        const writer = new PdfPageStore(data);
        const reader = new PdfPageStore(data);
        writer.createPagesForFile({ fileId: "f", name: "doc", pageCount: 4 });

        expect(reader.numberOfPages).toBe(4);
        expect(reader.sortedPageIds).toEqual(writer.sortedPageIds);
        expect(() => reader.checkInvariants()).not.toThrow();
    });
});
