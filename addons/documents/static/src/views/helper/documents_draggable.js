/** @odoo-module native */
import { markup } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { DRAGGED_CLASS, makeDraggableHook } from "@web/core/utils/dnd";
import { createDocumentFragmentFromContent } from "@web/core/utils/dom/html";
import { closestScrollableX, closestScrollableY } from "@web/core/utils/dom/scrolling";
import { toFolderValueId } from "@documents/views/utils";

/**
 * @param {Object} params
 * @param {{movableRecordIds: number[], nonMovableRecordIds: number[]}} params.draggedRecords
 * @param {Object|false} params.targetFolder
 * @param {boolean} params.userIsDocumentManager
 * @param {(folder: Object) => Object[]} params.getFolderAndParents
 * @returns {String}
 */
export function dropRejectionReason({
    draggedRecords,
    targetFolder,
    userIsDocumentManager,
    getFolderAndParents,
}) {
    if (!targetFolder || ["RECENT", "SHARED"].includes(targetFolder.id)) {
        return _t("You can't create shortcuts in nor move documents to this special folder.");
    }
    if (draggedRecords.nonMovableRecordIds.length && targetFolder.id === "TRASH") {
        return _t("There is at least one document you cannot move to trash in your selection.");
    }
    const canWrite =
        targetFolder.id === "COMPANY"
            ? targetFolder.user_permission === "edit" || userIsDocumentManager
            : typeof targetFolder.id !== "number" || targetFolder.user_permission === "edit";
    if (!canWrite) {
        return _t("You don't have the rights to write in this folder.");
    }
    const ancestorIds = getFolderAndParents(targetFolder).map((folder) => folder.id);
    if (draggedRecords.movableRecordIds.some((id) => ancestorIds.includes(id))) {
        return _t("You cannot move a folder into itself or a children.");
    }
    return "";
}

export const useDraggableDocuments = makeDraggableHook({
    name: "useDraggableDocuments",
    acceptedParams: {
        model: [Object],
        targetSelector: [String],
    },

    onComputeParams({ ctx, params }) {
        ctx.model = params.model;
        ctx.targetSelector = params.targetSelector;
        ctx.edgeScrolling.force = true;
        ctx.followCursor = false;
    },

    onWillStartDrag({ ctx }) {
        ctx.tempDraggedElements = [];
        ctx.initialPositions = [];
        ctx.selectedElements = [];
        ctx.draggedRecords = null;
        ctx.lastDragTime = 0;
        ctx.isInvalidTarget = false;
    },

    onDragStart({ ctx, callHandler, addClass, addCleanup, addStyle, addListener, removeClass }) {
        const { current, model, ref, targetSelector } = ctx;
        const { element } = current;
        addClass(ref.el, "o_documents_dragging");
        removeClass(element, DRAGGED_CLASS);
        const searchPanelEl = document.querySelector(".o_documents_search_panel");
        const currentElementId = parseInt(element.dataset.valueId);
        const currentRecord = model.root.records.find((r) => r.data.id === currentElementId);
        if (!currentRecord) {
            return;
        }

        if (
            !model.root.selection.length ||
            !model.root.selection.map((r) => r.data.id).includes(currentElementId)
        ) {
            model.root.selection.forEach((r) => (r.selected = false));
            currentRecord.selected = true;
        }
        this._setDraggedRecords(ctx, model);

        const recordData = currentRecord.data;
        current.dragMessageText = recordData.display_name;
        current.dragMessage = this._createDnDElement(recordData, model.root.selection.length);
        ref.el.append(current.dragMessage);

        const allElements = ref.el.classList.contains("o_kanban_renderer")
            ? ref.el.querySelectorAll(".o_kanban_record:not(.o_kanban_ghost)")
            : ref.el.querySelectorAll(".o_data_row");
        ctx.selectedElements = Array.from(allElements).filter((el) =>
            ctx.draggedRecords.all.includes(parseInt(el.dataset.valueId))
        );
        for (const selectedEl of ctx.selectedElements) {
            const sourceRect = selectedEl.getBoundingClientRect();
            const sourceName = model.root.records.find(
                (r) => r.data.id === parseInt(selectedEl.dataset.valueId)
            ).data.name;
            ctx.initialPositions.push({
                initialTop: sourceRect.top,
                initialLeft: sourceRect.left,
            });

            const tempEl = document.createElement("div");
            tempEl.innerText = sourceName;
            tempEl.classList.add("o_record_temporary");
            ctx.tempDraggedElements.push(tempEl);
            document.body.append(tempEl);
            addCleanup(() => tempEl.remove());

            tempEl.style.left = `${sourceRect.left}px`;
            tempEl.style.top = `${sourceRect.top}px`;

            addStyle(selectedEl, { opacity: 0.3 });
        }
        addStyle(current.dragMessage, { opacity: 1 });
        setTimeout(() => {
            ctx.tempDraggedElements.forEach((temp) => temp.remove());
            ctx.tempDraggedElements = [];
        }, 250);

        const switchContainer = (container) => {
            current.container = container;
            [current.scrollParentX, current.scrollParentY] = [
                closestScrollableX(container),
                closestScrollableY(container),
            ];
        };

        const onSearchPanelFolderPointerOver = (ev) => {
            const targetClasses = ev.target.classList;
            if (
                targetClasses.contains("o_search_panel_label") ||
                targetClasses.contains("o_search_panel_label_title") ||
                targetClasses.contains("w-100")
            ) {
                const valueEl = ev.target.closest(".o_search_panel_category_value");
                const targetFolder = model.env.searchModel.getFolderById(
                    toFolderValueId(valueEl.dataset.valueId)
                );
                this._checkTargetValidity(
                    ctx,
                    targetFolder,
                    model,
                    current.dragMessage,
                    current.dragMessageText,
                    true
                );
                if (!ev.ctrlKey) {
                    ref.el.classList.remove("o_documents_dnd_shortcut");
                }

                const allSelected = searchPanelEl.querySelectorAll(":scope .o_drag_over_selector");
                for (const selected of allSelected) {
                    selected.classList.remove("o_drag_over_selector");
                }
                addClass(valueEl, "o_drag_over_selector");
                if (!ctx.isInvalidTarget) {
                    model.env.documentsView.bus.trigger("documents-expand-folder", {
                        folderId: targetFolder.id,
                    });
                }
            }
        };

        const onSearchPanelFolderPointerEnter = () => {
            switchContainer(searchPanelEl);
        };

        const onSearchPanelFolderPointerLeave = () => {
            switchContainer(ref.el);
            if (ctx.isInvalidTarget) {
                ctx.isInvalidTarget = false;
                this._resetDragMessage(current.dragMessage, current.dragMessageText);
            }
            const allSelected = searchPanelEl.querySelectorAll(":scope .o_drag_over_selector");
            for (const selected of allSelected) {
                selected.classList.remove("o_drag_over_selector");
            }
        };

        const onTargetFolderPointerEnter = (ev) => {
            const targetFolder = model.env.searchModel.getFolderById(
                toFolderValueId(ev.currentTarget.dataset.valueId)
            );
            this._checkTargetValidity(
                ctx,
                targetFolder,
                model,
                current.dragMessage,
                current.dragMessageText
            );

            callHandler("onTargetPointerEnter", {
                target: ev.currentTarget,
                isInvalid: ctx.isInvalidTarget,
            });
        };

        const onTargetFolderPointerLeave = (ev) => {
            if (ctx.isInvalidTarget) {
                ctx.isInvalidTarget = false;
                this._resetDragMessage(current.dragMessage, current.dragMessageText);
            }
            callHandler("onTargetPointerLeave", { target: ev.currentTarget });
        };

        for (const targetFolder of ref.el.querySelectorAll(targetSelector)) {
            addListener(targetFolder, "pointerenter", onTargetFolderPointerEnter);
            addListener(targetFolder, "pointerleave", onTargetFolderPointerLeave);
        }
        if (searchPanelEl) {
            addListener(searchPanelEl, "pointerover", onSearchPanelFolderPointerOver);
            addListener(searchPanelEl, "pointerenter", onSearchPanelFolderPointerEnter);
            addListener(searchPanelEl, "pointerleave", onSearchPanelFolderPointerLeave);
        }

        this._updateDragInfoPosition(ctx, addStyle);

        addCleanup(() => {
            current.dragMessage.remove();
        });
    },

    onDrag({ ctx, addStyle }) {
        this._updateDragInfoPosition(ctx, addStyle);
        if (ctx.tempDraggedElements?.length) {
            const now = Date.now();
            if (now - ctx.lastDragTime >= 50) {
                ctx.lastDragTime = now;
                this._updateTempElementsAnimation(ctx);
            }
        }
    },

    async onDrop({ ctx, target }) {
        const { model, ref } = ctx;

        if (!ctx.current.dragMessage) {
            return;
        }
        if (ctx.isInvalidTarget) {
            return;
        }
        const targetElement =
            target.closest(".o_search_panel_category_value") ||
            target.closest(".o_kanban_record") ||
            target.closest(".o_data_row");
        if (!targetElement) {
            return;
        }
        if (targetElement.dataset.valueId === "TRASH") {
            if (
                ctx.draggedRecords.movableRecordIds.length &&
                (await model.documentService.moveToTrash(ctx.draggedRecords.movableRecordIds))
            ) {
                model.env.services.notification.add(
                    _t(
                        "%s document(s) sent to trash.",
                        ctx.draggedRecords.movableRecordIds.length
                    ),
                    { type: "success" }
                );
            }
            await model.env.searchModel._reloadSearchModel(true);
            return;
        }
        const targetFolderId = toFolderValueId(targetElement.dataset.valueId);
        const sourceFolder = model.env.searchModel.getSelectedFolder();
        const targetFolder = model.env.searchModel.getFolderById(targetFolderId);

        if (sourceFolder === targetFolder) {
            return;
        }

        if (
            ["RECENT", "SHARED", "TRASH"].includes(targetFolder?.id) ||
            ctx.draggedRecords.all.includes(targetFolder?.id) ||
            this._dropRejectionReason(ctx, targetFolder, model)
        ) {
            return;
        }

        if (targetFolder.id === "COMPANY") {
            await model.documentService.moveToCompanyRoot(ctx.draggedRecords);
            model.env.searchModel._reloadSearchModel(true);
            return;
        }

        let expectedAccessRightsChanges = false;
        if (
            !isNaN(targetFolder.id) &&
            this._getMovableRecords(model).some(
                (record) =>
                    record.data.access_internal !== targetFolder.access_internal ||
                    record.data.access_via_link !== targetFolder.access_via_link ||
                    (targetFolder.access_via_link !== "none" &&
                        record.data.is_access_via_link_hidden !==
                            targetFolder.is_access_via_link_hidden)
            )
        ) {
            expectedAccessRightsChanges = true;
        }

        await model.documentService.moveOrCreateShortcut(
            ctx.draggedRecords,
            targetFolder,
            ref.el.classList.contains("o_documents_dnd_shortcut"),
            expectedAccessRightsChanges
        );

        await model.load();
        await model.notify();
        await model.env.searchModel._reloadSearchModel(true);
    },

    _getMovableRecords(model) {
        return model.root.selection.filter(
            (record) => !record.data.lock_uid && record.data.user_permission === "edit"
        );
    },

    _setDraggedRecords(ctx, model) {
        const movableRecordIds = this._getMovableRecords(model).map((record) => record.data.id);
        const nonMovableRecordIds = model.root.selection
            .filter((record) => !movableRecordIds.includes(record.data.id))
            .map((record) => record.data.id);
        ctx.draggedRecords = {
            movableRecordIds,
            nonMovableRecordIds,
            all: [...movableRecordIds, ...nonMovableRecordIds],
        };
    },

    _createDnDElement(recordData, documentsCount) {
        const docCountPill =
            documentsCount > 1
                ? markup`<div class="o_documents_dnd_pill bg-success border border-light rounded-circle p-1 text-center">${documentsCount}</div>`
                : "";
        return createDocumentFragmentFromContent(markup`
            <span class="o_documents_dnd o_documents_dnd_info d-flex p-2">
                <i class="o_documents_mimetype_icon o_image" data-mimetype=${recordData.mimetype} title=${recordData.mimetype}></i>
                <span class="o_documents_dnd_text ps-2">${recordData.display_name}</span>
                <div class="o_documents_dnd_pill_container d-flex position-absolute top-0 start-100 translate-middle">
                    <div class="o_documents_dnd_pill o_documents_dnd_modifier bg-info border border-light rounded-circle p-1">
                        <i class="fa-solid fa-square-up-right"></i>
                    </div>
                    ${docCountPill}
                </div>
            </span>
        `).body.firstChild;
    },

    /**
     * @returns {String}
     */
    _dropRejectionReason(ctx, targetFolder, model) {
        return dropRejectionReason({
            draggedRecords: ctx.draggedRecords,
            targetFolder,
            userIsDocumentManager: model.documentService.userIsDocumentManager,
            getFolderAndParents: (folder) => model.env.searchModel.getFolderAndParents(folder),
        });
    },

    _checkTargetValidity(ctx, targetFolder, model, dragMessage, dragMessageText, reset = false) {
        const errorMessage = this._dropRejectionReason(ctx, targetFolder, model);
        ctx.isInvalidTarget = Boolean(errorMessage);
        if (errorMessage) {
            this._setErrorMessage(dragMessage, errorMessage);
        } else if (reset) {
            this._resetDragMessage(dragMessage, dragMessageText);
        }
    },

    _setErrorMessage(dragMessage, errorMessage) {
        dragMessage.classList.remove("o_documents_dnd_info");
        dragMessage.classList.add("alert", "alert-warning");
        dragMessage.querySelector(".o_documents_dnd_text").textContent = errorMessage;
    },

    _resetDragMessage(dragMessage, dragMessageText) {
        dragMessage.classList.remove("alert", "alert-warning");
        dragMessage.classList.add("o_documents_dnd_info");
        dragMessage.querySelector(".o_documents_dnd_text").textContent = dragMessageText;
    },

    _updateDragInfoPosition(ctx, addStyle) {
        const { dragMessage } = ctx.current;
        if (!dragMessage) {
            return;
        }
        addStyle(dragMessage, {
            left: `${ctx.pointer.x}px`,
            top: `${ctx.pointer.y}px`,
        });
    },

    _updateTempElementsAnimation(ctx) {
        const { dragMessage } = ctx.current;
        if (!dragMessage) {
            return;
        }
        const { width, height } = dragMessage.getBoundingClientRect();
        ctx.tempDraggedElements.forEach((clone, index) => {
            const initialPos = ctx.initialPositions[index];
            if (!initialPos) {
                return;
            }
            const dx = ctx.pointer.x - initialPos.initialLeft;
            const dy = ctx.pointer.y - initialPos.initialTop;

            clone.style.transform = `translate(${dx}px, ${dy}px)`;
            clone.style.width = `${width}px`;
            clone.style.height = `${height}px`;
        });
    },
});
