/** @odoo-module native */
import { _t } from "@web/core/translation";
import { uniqueId } from "@web/core/utils/functions";

/**
 * @returns {Object}
 */
export function makePdfPageStoreData() {
    return {
        pages: {},
        groupData: {},
        groupIds: [],
        numberOfPages: 0,
        focusedPage: undefined,
        lastSelectedPage: undefined,
    };
}

export class PdfPageStore {
    /**
     * @param {Object} [data]
     */
    constructor(data = makePdfPageStoreData()) {
        this.data = data;
    }

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
     * @returns {String[]}
     */
    get sortedPageIds() {
        return this.data.groupIds.flatMap((groupId) => [
            ...this.data.groupData[groupId].pageIds,
        ]);
    }
    /**
     * @returns {String[]}
     */
    get selectedPageIds() {
        return Object.keys(this.data.pages).filter(
            (pageId) =>
                this.data.pages[pageId].isSelected && this.data.pages[pageId].groupId,
        );
    }
    /**
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
     * @param {String} pageId
     * @returns {Object|undefined}
     */
    getGroupOfPage(pageId) {
        const page = this.data.pages[pageId];
        return page && page.groupId ? this.data.groupData[page.groupId] : undefined;
    }
    /**
     * @param {String} pageId
     * @returns {boolean}
     */
    isLastPageOfGroup(pageId) {
        const group = this.getGroupOfPage(pageId);
        return Boolean(group) && group.pageIds[group.pageIds.length - 1] === pageId;
    }

    /**
     * @param {Object} [param0]
     * @param {String} [param0.name]
     * @param {String[]} [param0.pageIds]
     * @param {number} [param0.index]
     * @param {boolean} [param0.isSelected]
     * @returns {String}
     */
    createGroup({ name, pageIds, index, isSelected } = {}) {
        const groupId = uniqueId("group");
        this.data.groupData[groupId] = {
            groupId,
            name: name || _t("New Group"),
            pageIds: [],
        };
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
    clearGroups() {
        for (const page of Object.values(this.data.pages)) {
            page.groupId = false;
        }
        this.data.groupData = {};
        this.data.groupIds = [];
        this.data.numberOfPages = 0;
    }
    /**
     * @param {Object} [param0]
     * @param {String} [param0.name]
     * @param {boolean} [param0.isSelected]
     * @returns {String}
     */
    regroupAll({ name, isSelected } = {}) {
        const allPageIds = this.sortedPageIds;
        this.clearGroups();
        return this.createGroup({ name, pageIds: allPageIds, isSelected });
    }
    /**
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
            const targetGroupId = this.data.groupIds[groupIndex + 1];
            if (!targetGroupId) {
                return;
            }
            for (const movedPageId of [...this.data.groupData[targetGroupId].pageIds]) {
                this.addPage(movedPageId, groupId);
            }
        } else {
            const followingPageIds = group.pageIds.slice(pageIndex + 1);
            const newGroupId = this.createGroup({ index: groupIndex + 1 });
            for (const movedPageId of followingPageIds) {
                this.addPage(movedPageId, newGroupId);
            }
        }
    }
    /**
     * @param {Object} param0
     * @param {String} param0.blankName
     * @param {Function} param0.subDocName
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

    /**
     * @param {Object} param0
     * @param {String} param0.fileId
     * @param {String} param0.name
     * @param {number} param0.pageCount
     * @param {boolean} [param0.groupPerPage]
     * @returns {Object}
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
     * @param {String} pageId
     * @param {String} groupId
     * @param {Object} [param2]
     * @param {number} [param2.index]
     * @returns {boolean}
     */
    addPage(pageId, groupId, { index } = {}) {
        const group = this.data.groupData[groupId];
        const page = this.data.pages[pageId];
        if (!group || !page) {
            return false;
        }
        this._detach(pageId, { keepGroup: groupId });
        if (index !== undefined) {
            group.pageIds.splice(index, 0, pageId);
        } else {
            group.pageIds.push(pageId);
        }
        page.groupId = groupId;
        this.data.numberOfPages += 1;
        return true;
    }
    /**
     * @param {String} pageId
     * @param {String} targetPageId
     * @returns {boolean}
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
            index -= 1;
        }
        return this.addPage(pageId, targetPage.groupId, { index });
    }
    /**
     * @param {String} pageId
     * @returns {boolean}
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
     * @param {String} pageId
     */
    deletePage(pageId) {
        this.removePage(pageId);
        delete this.data.pages[pageId];
    }

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
    toggleSelectAll() {
        this.selectAll(!this.allSelected);
    }
    unselectAll() {
        for (const pageId of this.selectedPageIds) {
            this.data.pages[pageId].isSelected = false;
        }
    }
    /**
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
     * @param {String} direction
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

    /**
     * @param {String} direction
     * @param {boolean} doSelect
     * @param {Function} [getCardsPerLine]
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
                return;
            }
            this.data.focusedPage = firstPageId;
            if (doSelect) {
                pages[firstPageId].isSelected = !pages[firstPageId].isSelected;
            }
        }
    }
    /**
     * @param {String} direction
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

    /**
     * @throws {Error}
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

    /**
     * @private
     * @param {String} pageId
     * @param {Object} [param1]
     * @param {String} [param1.keepGroup]
     */
    _detach(pageId, { keepGroup } = {}) {
        const page = this.data.pages[pageId];
        if (!page) {
            return;
        }
        const groupId = page.groupId;
        const group = groupId && this.data.groupData[groupId];
        page.groupId = false;
        if (!group) {
            return;
        }
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
