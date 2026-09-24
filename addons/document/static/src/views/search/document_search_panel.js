/** @odoo-module native */
import { AccessRightsUpdateConfirmationDialog } from "@document/owl/components/access_update_confirmation_dialog/access_update_confirmation_dialog";
import { _t } from "@web/core/translation";
import { browser } from "@web/core/browser/browser";
import { SearchPanel } from "@web/search/search_panel/search_panel";
import { useNestedSortable } from "@web/core/utils/dnd";
import { usePopover } from "@web/ui/popover";
import { useBus, useService } from "@web/core/utils/hooks";
import { utils as uiUtils } from "@web/ui/viewport";
import { toFolderValueId } from "@document/views/utils";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useViewModel } from "@web/model/model";
import { useSearchModel } from "@web/search/search_model";

const DND_ALLOWED_SPECIAL_DESTINATIONS = ["COMPANY", "MY"];
const LONG_TOUCH_THRESHOLD = 400;

export class DocumentsSearchPanelItemSettingsPopover extends Component {
    static template = "document.DocumentsSearchPanelItemSettingsPopover";
    static props = [
        "close",
        "createChildEnabled",
        "onCreateChild",
        "onEdit",
        "isShareable",
        "onShare",
        "isEditable",
    ];
}

export class DocumentsSearchPanel extends SearchPanel {
    static modelExtension = "DocumentsSearchPanel";
    static get template() {
        return !uiUtils.isSmall()
            ? "document.SearchPanel"
            : "document.SearchPanel.Small";
    }
    static get subTemplates() {
        return !uiUtils.isSmall()
            ? {
                  section: "web.SearchPanel.Section",
                  category: "document.SearchPanel.Category",
                  filtersGroup: "document.SearchPanel.FiltersGroup",
              }
            : {
                  section: "web.SearchPanel.Section",
                  category: "document.SearchPanel.Category.Small",
                  filtersGroup: "document.SearchPanel.FiltersGroup.Small",
              };
    }
    static rootIcons = {
        false: "fa-regular fa-folder",
        COMPANY: "fa-solid fa-building",
        MY: "fa-solid fa-hard-drive",
        RECENT: "fa-regular fa-clock",
        SHARED: "fa-solid fa-users",
        TRASH: "fa-solid fa-trash",
    };
    setup() {
        super.setup(...arguments);
        this.searchModel = useSearchModel();
        this.model = useViewModel();
        const { uploads } = useService("file_upload");
        this.documentService = useService("document.document");
        this.documentUploads = useState(uploads);
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.action = useService("action");
        this.popover = usePopover(DocumentsSearchPanelItemSettingsPopover, {
            onClose: () => this.onPopoverClose?.(),
            class: "o_search_panel_item_settings_popover",
        });
        this.dialog = useService("dialog");

        onWillStart(async () => {
            await this.searchModel.sectionsPromise;
            if (this.model.config.context.active_model) {
                const categories = await this.searchModel.getSections(
                    (s) => s.type === "category",
                );
                for (const category of categories) {
                    this.state.expanded[category.id] = {};
                }
            } else {
                const selectedFolderId = await this.searchModel.getSelectedFolderId();
                if (selectedFolderId) {
                    this.state.expanded[this.sections[0].id]["COMPANY"] = true;
                    this._expandFolder({ folderId: selectedFolderId });
                }
            }
        });

        useBus(this.env.documentsView.bus, "documents-expand-folder", (ev) => {
            this._expandFolder(ev.detail);
        });

        useBus(this.searchModel, "update-search-panel", async () => {
            this.updateActiveValues();
            this.state.searchModelUpdates++;
        });

        useNestedSortable({
            ref: this.root,
            groups: ".o_search_panel_category",
            elements: "li:not(.o_all_or_trash_category)",
            enable: () => this.documentService.userIsInternal,
            nest: true,
            nestInterval: 10,
            /**
             * @param {HTMLElement} parent
             * @param {HTMLElement} newGroup
             * @param {{parent: HTMLElement}} prevPos
             * @param {HTMLElement} placeholder
             */
            onMove: ({ parent, newGroup, prevPos, placeholder }) => {
                if (parent) {
                    parent.classList.add("o_has_treeEntry");
                    placeholder.classList.add("o_treeEntry");
                    const parentSectionId = parseInt(newGroup.dataset.sectionId);
                    const parentValueId = parseInt(parent.dataset.valueId);
                    this.state.expanded[parentSectionId][parentValueId] = true;
                } else {
                    placeholder.classList.remove("o_treeEntry");
                }
                if (prevPos.parent && !prevPos.parent.querySelector("li")) {
                    prevPos.parent.classList.remove("o_has_treeEntry");
                }
            },
            onDrop: async ({ element, parent, next }) => {
                const draggingFolderId = parseInt(element.dataset.valueId);
                const draggingFolder = this.searchModel.getFolderById(draggingFolderId);
                const draggingFolderRootId = draggingFolder.rootId;
                let parentFolderId = parent ? parent.dataset.valueId : false;
                const beforeFolderId = next ? parseInt(next.dataset.valueId) : false;
                if (
                    draggingFolderId === parseInt(parentFolderId) ||
                    isNaN(draggingFolderId) ||
                    !parentFolderId ||
                    this._notifyWrongDropDestination(parentFolderId)
                ) {
                    return;
                }
                const parentFolderRootId = this.searchModel.getFolderById(
                    toFolderValueId(parentFolderId),
                ).rootId;
                if (
                    !this.documentService.userIsDocumentManager &&
                    (!parentFolderRootId || parentFolderRootId === "COMPANY")
                ) {
                    return;
                }
                if (parentFolderRootId === "MY" && draggingFolderRootId !== "MY") {
                    await this.orm.call(
                        "document.document",
                        "action_create_shortcut",
                        [draggingFolderId],
                        { location_user_folder_id: parentFolderId.toString() },
                    );
                    return this.searchModel._reloadSearchModel(true);
                }
                if (!DND_ALLOWED_SPECIAL_DESTINATIONS.includes(parentFolderId)) {
                    parentFolderId = parseInt(parentFolderId);
                }
                const parentFolder = this.searchModel.getFolderById(parentFolderId);
                if (
                    !DND_ALLOWED_SPECIAL_DESTINATIONS.includes(parentFolderId) &&
                    (draggingFolder.access_internal !== parentFolder.access_internal ||
                        draggingFolder.access_via_link !==
                            parentFolder.access_via_link ||
                        (parentFolder.access_via_link !== "none" &&
                            draggingFolder.is_access_via_link_hidden !==
                                parentFolder.is_access_via_link_hidden))
                ) {
                    this.dialog.add(AccessRightsUpdateConfirmationDialog, {
                        destinationFolder: parentFolder,
                        confirm: async () => {
                            await this.orm.call(
                                "document.document",
                                "action_move_folder",
                                [
                                    [draggingFolderId],
                                    parentFolderId.toString() || false,
                                    beforeFolderId,
                                ],
                            );
                            await this.searchModel._reloadSearchModel(true);
                        },
                        cancel: () => {},
                    });
                    return;
                }
                await this.orm.call("document.document", "action_move_folder", [
                    [draggingFolderId],
                    parentFolderId ? parentFolderId.toString() : false,
                    beforeFolderId,
                ]);
                await this.searchModel._reloadSearchModel(true);
            },
        });
    }

    /**
     * @param {number|String} folderId
     * @returns {boolean}
     */
    isUploadingInFolder(folderId) {
        return Object.values(this.documentUploads).some(
            (upload) => upload.targetFolderId === folderId,
        );
    }

    /**
     * @param {Object} category
     * @param {Object} value
     */
    async toggleCategory(category, value) {
        if (category.activeValueId !== value.id) {
            const folder = this.searchModel.getFolderById(value.id);
            const isShortcut = !!folder.shortcut_document_id?.length;
            if (
                isShortcut &&
                !this.searchModel.getFolderById(folder.shortcut_document_id[0])
            ) {
                return this.searchModel.toggleCategoryValue(category.id, "TRASH");
            }
            this.searchModel.toggleCategoryValue(category.id, value.id);
        }
    }

    /**
     * @param {*} category
     * @param {*} value
     */
    async toggleFold(category, value) {
        if (value.childrenIds.length) {
            const categoryState = this.state.expanded[category.id];
            categoryState[value.id] = !categoryState[value.id];
        } else {
            this.getDropdownState(category.id).close();
        }
    }

    resetLongTouchTimer() {
        if (this.longTouchTimer) {
            browser.clearTimeout(this.longTouchTimer);
            this.longTouchTimer = null;
        }
    }

    onSectionValueTouchStart(ev, section, value) {
        if (!uiUtils.isSmall() || typeof value !== "number") {
            return;
        }
        this.touchStartMs = Date.now();
        if (!this.longTouchTimer) {
            this.longTouchTimer = browser.setTimeout(() => {
                this.openEditPopover?.(ev, section, value);
                this.resetLongTouchTimer();
            }, LONG_TOUCH_THRESHOLD);
        }
    }

    onSectionValueTouchEnd() {
        const elapsedTime = Date.now() - this.touchStartMs;
        if (elapsedTime < LONG_TOUCH_THRESHOLD) {
            this.resetLongTouchTimer();
        }
    }

    onSectionValueTouchMove() {
        this.resetLongTouchTimer();
    }

    /**
     * @param {Object} param0
     * @param {number|String} param0.folderId
     */
    _expandFolder({ folderId }) {
        const sectionId = this.sections[0].id;
        const folders = this.searchModel.getFolderAndParents(
            this.searchModel.getFolderById(folderId),
        );
        if (!folders.length) {
            return;
        }
        if (
            folders[0].id === "COMPANY" ||
            this.state.expanded[sectionId][folders[0].rootId]
        ) {
            for (const folder of folders) {
                this.state.expanded[sectionId][folder.id] = true;
            }
        }
    }

    _notifyWrongDropDestination(folderId) {
        if (isNaN(folderId) && !DND_ALLOWED_SPECIAL_DESTINATIONS.includes(folderId)) {
            this.notification.add(
                _t(
                    "You can't create shortcuts in or move documents to this special folder.",
                ),
                {
                    title: _t("Invalid operation"),
                    type: "warning",
                },
            );
            return true;
        }
    }
}
