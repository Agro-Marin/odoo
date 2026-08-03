/** @odoo-module native */
import { _t } from "@web/core/translation";
import { uniqueId } from "@web/core/utils/functions";

/**
 * Build the plain data container a {@link PdfPageStore} operates on.
 *
 * Kept separate from the store so the caller decides whether the container is
 * plain (unit tests) or wrapped in an OWL `reactive`/`useState` proxy (the
 * component). The store itself never creates or inspects a proxy.
 *
 * Only serialisable bookkeeping lives in here: no canvas, no pdf.js proxy, no
 * DOM node. That is deliberate — `state.pageCanvases` holds both of those
 * inside a reactive and is the reason `toRaw()` has to be sprinkled over the
 * render paths.
 *
 * @returns {Object}
 */
export function makePdfPageStoreData() {
    return {
        /** pages[pageId] = { pageId, groupId, fileId, localPageNumber, isSelected, isBlank } */
        pages: {},
        /** groupData[groupId] = { groupId, name, pageIds } */
        groupData: {},
        /** Ordered list of group ids. */
        groupIds: [],
        /** Number of *grouped* pages. Maintained incrementally, never recomputed. */
        numberOfPages: 0,
        /** Id of the page that currently has the focus, if any. */
        focusedPage: undefined,
        /** Id of the last page the user selected, if any. */
        lastSelectedPage: undefined,
    };
}

/**
 * Sole owner of the PDF split tool's page/group bookkeeping.
 *
 * `pages`, `groupData`, `groupIds` and `numberOfPages` are four mutually
 * dependent structures, and every way they can drift apart produces a user
 * visible defect (pages duplicated across groups after a failed split, a crash on
 * an already-detached page, forward drags landing one slot late, a quadratic page
 * counter). This class is their single writer, so those states are not
 * representable.
 *
 * Invariants, all enforced here and checked by {@link checkInvariants}:
 *  1. a page belongs to at most one group — attaching detaches first;
 *  2. `numberOfPages` equals the number of grouped pages, maintained by +/- 1
 *     on every attach/detach (never by recounting: that made the callers that
 *     loop over pages quadratic);
 *  3. a group's `pageIds` holds no unknown id and no duplicate, and every
 *     listed page points back at the group;
 *  4. a group that loses its last page is removed from `groupIds`;
 *  5. `focusedPage` / `lastSelectedPage` never reference a detached page.
 *
 * Deliberately absent: DOM access, pdf.js, component props, OWL. The owning
 * component keeps rendering, canvases, hotkeys, drag-and-drop DOM, the preview
 * lightbox and the upload.
 */
export class PdfPageStore {
    /**
     * @param {Object} [data] container to operate on, see
     *   {@link makePdfPageStoreData}. Pass a reactive proxy to drive a render.
     */
    constructor(data = makePdfPageStoreData()) {
        this.data = data;
    }

    //--------------------------------------------------------------------------
    // Reads
    //--------------------------------------------------------------------------

    /** @returns {Object} */
    get pages() {
        return this.data.pages;
    }
    /** @returns {Object} */
    get groupData() {
        return this.data.groupData;
    }
    /** @returns {String[]} */
    get groupIds() {
        return this.data.groupIds;
    }
    /** @returns {number} */
    get numberOfPages() {
        return this.data.numberOfPages;
    }
    /** @returns {String|undefined} */
    get focusedPage() {
        return this.data.focusedPage;
    }
    set focusedPage(pageId) {
        this.data.focusedPage = pageId;
    }
    /** @returns {String|undefined} */
    get lastSelectedPage() {
        return this.data.lastSelectedPage;
    }
    set lastSelectedPage(pageId) {
        this.data.lastSelectedPage = pageId;
    }
    /**
     * Every grouped page id, in display order.
     * @returns {String[]}
     */
    get sortedPageIds() {
        return this.data.groupIds.flatMap((groupId) => [
            ...this.data.groupData[groupId].pageIds,
        ]);
    }
    /**
     * Grouped pages the user has selected: the ones a split commits.
     * @returns {String[]}
     */
    get selectedPageIds() {
        return Object.keys(this.data.pages).filter(
            (pageId) =>
                this.data.pages[pageId].isSelected && this.data.pages[pageId].groupId,
        );
    }
    /**
     * Grouped pages the user left out: the ones a split keeps in the tool.
     * @returns {String[]}
     */
    get ignoredPageIds() {
        return Object.keys(this.data.pages).filter(
            (pageId) =>
                !this.data.pages[pageId].isSelected && this.data.pages[pageId].groupId,
        );
    }
    /** @returns {boolean} */
    get allSelected() {
        return !Object.values(this.data.pages).some((page) => !page.isSelected);
    }
    /**
     * @param {String} pageId
     * @returns {Object|undefined}
     */
    getPage(pageId) {
        return this.data.pages[pageId];
    }
    /**
     * @param {String} groupId
     * @returns {Object|undefined}
     */
    getGroup(groupId) {
        return this.data.groupData[groupId];
    }
    /**
     * The group a page belongs to, if any.
     * @param {String} pageId
     * @returns {Object|undefined}
     */
    getGroupOfPage(pageId) {
        const page = this.data.pages[pageId];
        return page && page.groupId ? this.data.groupData[page.groupId] : undefined;
    }
    /**
     * Whether a page closes its group, i.e. whether a separator is drawn right
     * after it.
     *
     * The model-side truth behind the `o_pdf_separator_selected` class the template
     * puts on the splitter after a group's last page. Asked here rather than read
     * back off the DOM: grouping is this store's to answer, and a DOM round trip
     * needs a mounted component to be testable.
     *
     * @param {String} pageId
     * @returns {boolean}
     */
    isLastPageOfGroup(pageId) {
        const group = this.getGroupOfPage(pageId);
        return Boolean(group) && group.pageIds[group.pageIds.length - 1] === pageId;
    }

    //--------------------------------------------------------------------------
    // Groups
    //--------------------------------------------------------------------------

    /**
     * @param {Object} [param0]
     * @param {String} [param0.name]
     * @param {String[]} [param0.pageIds] pages to move into the new group
     * @param {number} [param0.index] position in `groupIds` (appended if absent)
     * @param {boolean} [param0.isSelected] forces the moved pages' selection
     * @returns {String} the new group id
     */
    createGroup({ name, pageIds, index, isSelected } = {}) {
        const groupId = uniqueId("group");
        this.data.groupData[groupId] = {
            groupId,
            name: name || _t("New Group"),
            pageIds: [],
        };
        // Register before filling: `addPage` resolves the group through
        // `groupData`, so it has to be reachable first.
        if (index !== undefined) {
            this.data.groupIds.splice(index, 0, groupId);
        } else {
            this.data.groupIds.push(groupId);
        }
        for (const pageId of pageIds || []) {
            if (this.addPage(pageId, groupId) && isSelected !== undefined) {
                this.data.pages[pageId].isSelected = isSelected;
            }
        }
        return groupId;
    }
    /**
     * Drop every group, detaching all pages. `pages` itself is untouched.
     */
    clearGroups() {
        // Clearing `page.groupId` matters: a page still pointing at a group
        // that no longer exists is exactly what let `createGroup` adopt a page
        // twice and inflate the counter.
        for (const page of Object.values(this.data.pages)) {
            page.groupId = false;
        }
        this.data.groupData = {};
        this.data.groupIds = [];
        this.data.numberOfPages = 0;
    }
    /**
     * Gather every page into one fresh group.
     * @param {Object} [param0]
     * @param {String} [param0.name]
     * @param {boolean} [param0.isSelected]
     * @returns {String} the new group id
     */
    regroupAll({ name, isSelected } = {}) {
        const allPageIds = this.sortedPageIds;
        this.clearGroups();
        return this.createGroup({ name, pageIds: allPageIds, isSelected });
    }
    /**
     * Toggle the separator that follows `pageId` inside `groupId`: either split
     * the group there, or merge the next group back in when `pageId` is last.
     * @param {String} pageId
     * @param {String} groupId
     */
    toggleSeparator(pageId, groupId) {
        const group = this.data.groupData[groupId];
        if (!group) {
            return;
        }
        const pageIndex = group.pageIds.indexOf(pageId);
        if (pageIndex === -1) {
            return;
        }
        const groupIndex = this.data.groupIds.indexOf(groupId);
        if (pageIndex === group.pageIds.length - 1) {
            // Last page of the group: merge the following group into this one.
            const targetGroupId = this.data.groupIds[groupIndex + 1];
            if (!targetGroupId) {
                return;
            }
            // Snapshot: `addPage` detaches each page from the target group as
            // it goes, which rewrites that group's `pageIds`.
            for (const movedPageId of [...this.data.groupData[targetGroupId].pageIds]) {
                this.addPage(movedPageId, groupId);
            }
        } else {
            // Split: everything after `pageId` moves to a new following group.
            const followingPageIds = group.pageIds.slice(pageIndex + 1);
            const newGroupId = this.createGroup({ index: groupIndex + 1 });
            for (const movedPageId of followingPageIds) {
                this.addPage(movedPageId, newGroupId);
            }
        }
    }
    /**
     * Rebuild the grouping from the blank pages, in display order.
     * @param {Object} param0
     * @param {String} param0.blankName name given to a run of blank pages
     * @param {Function} param0.subDocName (count) => name of a sub-document
     */
    splitOnBlankPages({ blankName, subDocName }) {
        const allPageIds = this.sortedPageIds;
        if (!allPageIds.length) {
            return;
        }
        let precedingPageIsBlank = false;
        let docCount = 1;
        this.clearGroups();
        this.createGroup({
            pageIds: allPageIds,
            name: this.data.pages[allPageIds[0]].isBlank
                ? blankName
                : subDocName(docCount++),
        });
        // Walk in display order (the snapshot above), not `pages` insertion
        // order, so drag-and-drop reordering is honoured and detached pages
        // left over from a partial split are never visited.
        for (const pageId of allPageIds) {
            const page = this.data.pages[pageId];
            const splitHere = (name) => {
                const groupPageIds = this.data.groupData[page.groupId].pageIds;
                this.createGroup({
                    name,
                    pageIds: groupPageIds.slice(groupPageIds.indexOf(pageId)),
                });
            };
            if (page.isBlank && !precedingPageIsBlank) {
                splitHere(blankName);
            } else if (!page.isBlank && precedingPageIsBlank) {
                splitHere(subDocName(docCount++));
            }
            page.isSelected = !page.isBlank;
            precedingPageIsBlank = page.isBlank;
        }
        // Drop whatever stayed empty (the initial catch-all when the first page
        // is blank). A lingering empty group makes focus navigation land on an
        // undefined page.
        for (const groupId of [...this.data.groupIds]) {
            this._removeGroupIfEmpty(groupId);
        }
    }
    /**
     * @param {String} groupId
     * @param {String} name
     */
    renameGroup(groupId, name) {
        const group = this.data.groupData[groupId];
        if (group) {
            group.name = name || _t("unnamed");
        }
    }

    //--------------------------------------------------------------------------
    // Pages
    //--------------------------------------------------------------------------

    /**
     * Create one page record per page of a freshly loaded file, and group them.
     * @param {Object} param0
     * @param {String} param0.fileId
     * @param {String} param0.name base name for the generated groups
     * @param {number} param0.pageCount
     * @param {boolean} [param0.groupPerPage] one group per page instead of one
     *   group for the whole file
     * @returns {Object} { pageIds: String[], newPages: {pageNumber: pageId} }
     */
    createPagesForFile({ fileId, name, pageCount, groupPerPage }) {
        let groupId;
        const pageIds = [];
        const newPages = {};
        for (let pageNumber = 0; pageNumber < pageCount; pageNumber++) {
            if (groupPerPage) {
                groupId = this.createGroup({ name: `${name}-p${pageNumber + 1}` });
            } else if (!groupId) {
                groupId = this.createGroup({ name });
            }
            const pageId = uniqueId("page");
            this.data.pages[pageId] = {
                pageId,
                // Attached through `addPage` below rather than set here, so the
                // page goes through the one code path that keeps the counter,
                // the group listing and `page.groupId` in agreement.
                groupId: false,
                fileId,
                localPageNumber: pageNumber + 1,
                isSelected: true,
            };
            this.addPage(pageId, groupId);
            newPages[pageNumber + 1] = pageId;
            pageIds.push(pageId);
        }
        return { pageIds, newPages };
    }
    /**
     * Attach a page to a group, detaching it from its current one first.
     * @param {String} pageId
     * @param {String} groupId
     * @param {Object} [param2]
     * @param {number} [param2.index] position inside the group (appended if absent)
     * @returns {boolean} whether the page was attached
     */
    addPage(pageId, groupId, { index } = {}) {
        const group = this.data.groupData[groupId];
        const page = this.data.pages[pageId];
        if (!group || !page) {
            // An unknown page id would otherwise be pushed into `pageIds` and
            // then dereferenced, i.e. a group listing a page that does not
            // exist — or a TypeError, depending on the call site.
            return false;
        }
        // `keepGroup`: a same-group move must not let the group vanish between
        // the detach and the re-attach.
        this._detach(pageId, { keepGroup: groupId });
        if (index !== undefined) {
            group.pageIds.splice(index, 0, pageId);
        } else {
            group.pageIds.push(pageId);
        }
        page.groupId = groupId;
        // Incremental. Recomputing from `sortedPageIds` here (a flatMap over
        // every group) is what made the callers that loop over pages quadratic:
        // 400 pages went from 998ms to 64ms when this became a +1.
        this.data.numberOfPages += 1;
        return true;
    }
    /**
     * Move a page to the position currently held by another page. Used by
     * drag-and-drop.
     * @param {String} pageId the dragged page
     * @param {String} targetPageId the page it is dropped onto
     * @returns {boolean} whether the page was moved
     */
    movePage(pageId, targetPageId) {
        const targetPage = this.data.pages[targetPageId];
        const targetGroup = targetPage && this.data.groupData[targetPage.groupId];
        if (!targetGroup || !this.data.pages[pageId]) {
            return false;
        }
        let index = targetGroup.pageIds.indexOf(targetPageId);
        const sourceIndex = targetGroup.pageIds.indexOf(pageId);
        if (sourceIndex !== -1 && sourceIndex < index) {
            // Same-group forward drag: the detach in `addPage` shifts
            // everything after the source one slot left, so the target's index
            // is stale by one. Without this the page landed *after* its target.
            index -= 1;
        }
        return this.addPage(pageId, targetPage.groupId, { index });
    }
    /**
     * Detach a page from its group. The page record survives; the tool keeps
     * showing nothing for it until it is re-attached or deleted.
     * @param {String} pageId
     * @returns {boolean} whether the page exists
     */
    removePage(pageId) {
        if (!this.data.pages[pageId]) {
            return false;
        }
        this._detach(pageId);
        this._forgetPageReferences(pageId);
        return true;
    }
    /**
     * Detach a page and drop its record entirely.
     * @param {String} pageId
     */
    deletePage(pageId) {
        this.removePage(pageId);
        delete this.data.pages[pageId];
    }

    //--------------------------------------------------------------------------
    // Selection
    //--------------------------------------------------------------------------

    /**
     * @param {String} pageId
     * @param {boolean} isSelected
     */
    setSelected(pageId, isSelected) {
        const page = this.data.pages[pageId];
        if (page) {
            page.isSelected = isSelected;
        }
    }
    /**
     * @param {String} pageId
     */
    toggleSelected(pageId) {
        const page = this.data.pages[pageId];
        if (page) {
            page.isSelected = !page.isSelected;
        }
    }
    /**
     * @param {boolean} isSelected
     */
    selectAll(isSelected) {
        for (const page of Object.values(this.data.pages)) {
            page.isSelected = isSelected;
        }
    }
    /**
     * Select everything, or deselect everything if it already is all selected.
     */
    toggleSelectAll() {
        this.selectAll(!this.allSelected);
    }
    /**
     * Deselect the grouped pages.
     */
    unselectAll() {
        for (const pageId of this.selectedPageIds) {
            this.data.pages[pageId].isSelected = false;
        }
    }
    /**
     * Select the whole group, or deselect it if it already is fully selected.
     * @param {String} groupId
     */
    toggleGroupSelection(groupId) {
        const group = this.data.groupData[groupId];
        if (!group) {
            return;
        }
        const isSelected = group.pageIds.some(
            (pageId) => this.data.pages[pageId].isSelected !== true,
        );
        for (const pageId of group.pageIds) {
            this.data.pages[pageId].isSelected = isSelected;
        }
    }
    /**
     * Toggle a page's selection through a user click, extending the selection
     * from the last clicked page when asked to.
     * @param {String} pageId
     * @param {Object} [param1]
     * @param {boolean} [param1.isRangeSelection]
     */
    clickSelect(pageId, { isRangeSelection } = {}) {
        const page = this.data.pages[pageId];
        if (!page) {
            return;
        }
        page.isSelected = !page.isSelected;
        if (isRangeSelection && this.data.lastSelectedPage && page.isSelected) {
            const sortedPageIds = this.sortedPageIds;
            const pageIndex = sortedPageIds.indexOf(pageId);
            const lastIndex = sortedPageIds.indexOf(this.data.lastSelectedPage);
            const pagesToSelect =
                pageIndex < lastIndex
                    ? sortedPageIds.slice(pageIndex, lastIndex + 1)
                    : sortedPageIds.slice(lastIndex, pageIndex + 1);
            for (const selectedPageId of pagesToSelect) {
                this.data.pages[selectedPageId].isSelected = true;
            }
        }
        this.data.lastSelectedPage = pageId;
    }
    /**
     * Select every page from the focused one to the group's edge, or deselect
     * them if that range already is fully selected.
     * @param {String} direction "left" or "right"
     */
    selectUntilSplit(direction) {
        if (this.data.focusedPage) {
            const group = this.getGroupOfPage(this.data.focusedPage);
            if (!group) {
                return;
            }
            const pageIndex = group.pageIds.indexOf(this.data.focusedPage);
            const pagesToSelect =
                direction === "right"
                    ? group.pageIds.slice(pageIndex)
                    : group.pageIds.slice(0, pageIndex + 1);
            const isFullySelected = pagesToSelect.every(
                (pageId) => this.data.pages[pageId].isSelected,
            );
            for (const pageId of pagesToSelect) {
                this.data.pages[pageId].isSelected = !isFullySelected;
            }
        } else if (this.data.lastSelectedPage) {
            this.data.focusedPage = this.data.lastSelectedPage;
            this.selectUntilSplit(direction);
        } else {
            this.data.focusedPage = this.sortedPageIds[0];
        }
    }

    //--------------------------------------------------------------------------
    // Focus
    //--------------------------------------------------------------------------

    /**
     * Move the focus by one step in display order.
     * @param {String} direction "left", "right", "up" or "down"
     * @param {boolean} doSelect also drag the selection along
     * @param {Function} [getCardsPerLine] how many cards a rendered line holds;
     *   only called for the vertical steps' stride, and only when it is needed
     *   (it is the component's single DOM measurement in this path)
     */
    focusNextPage(direction, doSelect, getCardsPerLine = () => 1) {
        const { focusedPage, lastSelectedPage, pages } = this.data;
        if (focusedPage) {
            const sortedPageIds = this.sortedPageIds;
            let nextFocusedPageId;
            if (!sortedPageIds.includes(focusedPage)) {
                nextFocusedPageId = sortedPageIds[0];
            } else {
                const cardsPerLine = getCardsPerLine();
                const shift = {
                    right: 1,
                    left: -1,
                    down: cardsPerLine,
                    up: -cardsPerLine,
                }[direction];
                nextFocusedPageId =
                    sortedPageIds[sortedPageIds.indexOf(focusedPage) + shift];
            }
            if (nextFocusedPageId) {
                if (doSelect) {
                    pages[focusedPage].isSelected =
                        !pages[nextFocusedPageId].isSelected;
                    pages[nextFocusedPageId].isSelected = true;
                }
                this.data.focusedPage = nextFocusedPageId;
            }
        } else if (lastSelectedPage) {
            this.data.focusedPage = lastSelectedPage;
            this.focusNextPage(direction, doSelect, getCardsPerLine);
        } else {
            const firstPageId = this.sortedPageIds[0];
            if (!firstPageId) {
                // No page at all (nothing loaded yet, or every load failed).
                return;
            }
            this.data.focusedPage = firstPageId;
            if (doSelect) {
                pages[firstPageId].isSelected = !pages[firstPageId].isSelected;
            }
        }
    }
    /**
     * Move the focus to the first page of the neighbouring group.
     * @param {String} direction "left" or "right"
     */
    focusNextGroup(direction) {
        if (this.data.focusedPage) {
            const page = this.data.pages[this.data.focusedPage];
            const index = this.data.groupIds.indexOf(page.groupId);
            const shift = direction === "right" ? 1 : -1;
            const neighbour = this.data.groupData[this.data.groupIds[index + shift]];
            if (neighbour) {
                this.data.focusedPage = neighbour.pageIds[0];
            }
        } else if (this.data.lastSelectedPage) {
            this.data.focusedPage = this.data.lastSelectedPage;
            this.focusNextGroup(direction);
        } else {
            this.data.focusedPage = this.sortedPageIds[0];
        }
    }

    //--------------------------------------------------------------------------
    // Consistency
    //--------------------------------------------------------------------------

    /**
     * Assert every invariant this class exists to hold. Not on any hot path:
     * it is O(pages + groups) and meant for tests and debugging.
     * @throws {Error} listing every violation found
     */
    checkInvariants() {
        const errors = [];
        const groupOfPage = new Map();
        let groupedCount = 0;
        for (const groupId of this.data.groupIds) {
            const group = this.data.groupData[groupId];
            if (!group) {
                errors.push(`groupIds lists unknown group ${groupId}`);
                continue;
            }
            if (!group.pageIds.length) {
                errors.push(`group ${groupId} is listed but empty`);
            }
            for (const pageId of group.pageIds) {
                groupedCount++;
                if (!this.data.pages[pageId]) {
                    errors.push(`group ${groupId} lists unknown page ${pageId}`);
                    continue;
                }
                if (groupOfPage.has(pageId)) {
                    errors.push(
                        `page ${pageId} is listed by both ${groupOfPage.get(pageId)} and ${groupId}`,
                    );
                }
                groupOfPage.set(pageId, groupId);
                if (this.data.pages[pageId].groupId !== groupId) {
                    errors.push(
                        `page ${pageId} does not point back at group ${groupId}`,
                    );
                }
            }
        }
        for (const groupId of Object.keys(this.data.groupData)) {
            if (!this.data.groupIds.includes(groupId)) {
                errors.push(`group ${groupId} exists but is not listed in groupIds`);
            }
        }
        for (const [pageId, page] of Object.entries(this.data.pages)) {
            if (page.groupId && groupOfPage.get(pageId) !== page.groupId) {
                errors.push(
                    `page ${pageId} claims group ${page.groupId}, which does not list it`,
                );
            }
        }
        if (groupedCount !== this.data.numberOfPages) {
            errors.push(
                `numberOfPages is ${this.data.numberOfPages} but ${groupedCount} pages are grouped`,
            );
        }
        for (const key of ["focusedPage", "lastSelectedPage"]) {
            const pageId = this.data[key];
            if (pageId && !groupOfPage.has(pageId)) {
                errors.push(`${key} references detached page ${pageId}`);
            }
        }
        if (errors.length) {
            throw new Error(
                `PdfPageStore invariants violated:\n- ${errors.join("\n- ")}`,
            );
        }
    }

    //--------------------------------------------------------------------------
    // Private
    //--------------------------------------------------------------------------

    /**
     * Remove a page from whatever group holds it, without touching the focus.
     *
     * Split from {@link removePage} on purpose: re-attaching a page (a reorder,
     * a merge) detaches it first, and that must not cost the user their focus.
     * Only a real removal releases the focus references.
     *
     * @private
     * @param {String} pageId
     * @param {Object} [param1]
     * @param {String} [param1.keepGroup] group to leave in place even if the
     *   detach empties it (the caller is about to fill it again)
     */
    _detach(pageId, { keepGroup } = {}) {
        const page = this.data.pages[pageId];
        if (!page) {
            return;
        }
        const groupId = page.groupId;
        // A page is legitimately group-less: already committed by a partial split,
        // or freshly created.
        const group = groupId && this.data.groupData[groupId];
        page.groupId = false;
        if (!group) {
            return;
        }
        // filter + reassign rather than an in-place splice: the reactive proxy
        // fires a set trap per shifted index, and splice measured ~2x slower on
        // a 400-group document. Callers rely on the reassignment too — it turns
        // a `pageIds` reference held across a loop into a stable snapshot.
        group.pageIds = group.pageIds.filter((listedPageId) => listedPageId !== pageId);
        this.data.numberOfPages -= 1;
        if (groupId !== keepGroup) {
            this._removeGroupIfEmpty(groupId);
        }
    }
    /**
     * @private
     * @param {String} groupId
     */
    _removeGroupIfEmpty(groupId) {
        const group = this.data.groupData[groupId];
        if (!group || group.pageIds.length > 0) {
            return;
        }
        // No scan over `pages` here: the group is empty, and `_detach` clears
        // `page.groupId` before getting here. The scan was O(all pages) on
        // every single page removal.
        this.data.groupIds = this.data.groupIds.filter(
            (listedGroupId) => listedGroupId !== groupId,
        );
        delete this.data.groupData[groupId];
    }
    /**
     * @private
     * @param {String} pageId
     */
    _forgetPageReferences(pageId) {
        if (this.data.focusedPage === pageId) {
            this.data.focusedPage = undefined;
        }
        if (this.data.lastSelectedPage === pageId) {
            this.data.lastSelectedPage = undefined;
        }
    }
}
