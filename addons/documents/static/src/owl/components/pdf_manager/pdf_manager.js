/** @odoo-module native */
import { ExitSplitToolsDialog } from "@documents/owl/components/pdf_exit_dialog/pdf_exit_dialog";
import { PdfGroupName } from "@documents/owl/components/pdf_group_name/pdf_group_name";
import {
    makePdfPageStoreData,
    PdfPageStore,
} from "@documents/owl/components/pdf_manager/pdf_page_store";
import { PdfPage } from "@documents/owl/components/pdf_page/pdf_page";
import { Component, onWillStart, toRaw, useEffect, useRef, useState } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown";
import { _t } from "@web/core/translation";
import { uniqueId } from "@web/core/utils/functions";
import { useService } from "@web/core/utils/hooks";
import { loadPDFJS, pdfjsLib } from "@web/core/utils/pdfjs";
import { useCommand } from "@web/ui/commands";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { useActiveElement } from "@web/ui/ui_service";
import { ConfirmationDialog, Dialog } from "@web/ui/dialog";

const BLANK_PAGE_THRESHOLD = 2500;
const BLANK_PIXEL_FILTER_VALUE = 220;
const NON_LEAVING_MENUS = ["shortcuts", "settings", "support", "documentation"];

export class PdfManager extends Component {
    static components = {
        Dialog,
        Dropdown,
        PdfPage,
        PdfGroupName,
    };
    static defaultProps = {
        embeddedActions: [],
    };
    static props = {
        documents: Array,
        embeddedActions: { type: Array, optional: true },
        onProcessDocuments: { type: Function },
        close: { type: Function },
    };
    static template = "documents.component.PdfManager";

    setup() {
        this.root = useRef("root");
        useActiveElement("root");
        this.pageViewer = useRef("pageViewer");
        this.pagePreview = useRef("pagePreview");
        this.selectionBox = useRef("selectionBox");
        this.addFileInput = useRef("addFileInput");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.store = new PdfPageStore(useState(makePdfPageStoreData()));
        this.state = useState({
            uploadingLock: false,
            pageCanvases: {},
            viewedPage: undefined,
            viewedPageName: undefined,
            viewedPageIndex: undefined,
            archive: true,
            keepDocument: true,
            fileName: "",
            edit: false,
            isSelecting: false,
            selectionBoxArgs: { left: "0px", top: "0px", width: "0px", height: "0px" },
        });

        this._exitSplitToolsClick = false;
        this._newFiles = {};
        this._selectionX = 0.0;
        this._selectionY = 0.0;
        this._selectionScrollTop = 0.0;
        this._selectionScrollLeft = 0.0;
        this._embeddedActionApplied = false;
        this._onMouseDown = this._onMouseDown.bind(this);
        this._onMouseUp = this._onMouseUp.bind(this);
        this._onMouseMove = this._onMouseMove.bind(this);
        this._onShiftDown = this._onShiftDown.bind(this);
        this._setUseCommand = this._setUseCommand.bind(this);
        this._exitSplitTools = this._exitSplitTools.bind(this);
        this._objectUrls = [];
        this._pdfDocuments = [];

        onWillStart(async () => {
            await this._loadAssets();
        });

        useEffect(
            () => {
                const _onOutsideClick = this._onOutsideClick.bind(this);
                if (this.props.documents.length === 1) {
                    this.state.fileName = this._removePdfExtension(
                        this.props.documents[0].name,
                    );
                }
                for (const pdf_document of this.props.documents) {
                    this._addFile(pdf_document.name, {
                        url: `/documents/content/${encodeURIComponent(pdf_document.access_token)}`,
                        documentId: pdf_document.id,
                    });
                }
                document.addEventListener("click", _onOutsideClick, true);
                document.addEventListener("mousedown", this._onMouseDown, true);
                document.addEventListener("mouseup", this._onMouseUp, true);
                document.addEventListener("mousemove", this._onMouseMove, true);
                document.addEventListener("keydown", this._onShiftDown, true);
                return () => {
                    document.removeEventListener("click", _onOutsideClick, true);
                    document.removeEventListener("mousedown", this._onMouseDown, true);
                    document.removeEventListener("mouseup", this._onMouseUp, true);
                    document.removeEventListener("mousemove", this._onMouseMove, true);
                    document.removeEventListener("keydown", this._onShiftDown, true);
                    for (const objectUrl of this._objectUrls) {
                        URL.revokeObjectURL(objectUrl);
                    }
                    for (const pdf of this._pdfDocuments) {
                        pdf.destroy();
                    }
                    this._objectUrls = [];
                    this._pdfDocuments = [];
                };
            },
            () => [],
        );

        this._setUseCommand(
            _t("Focus previous page"),
            this._focusNextPage.bind(this, "left", false),
            "arrowleft",
            {
                allowRepeat: true,
            },
        );
        this._setUseCommand(
            _t("Focus next page"),
            this._focusNextPage.bind(this, "right", false),
            "arrowright",
            {
                allowRepeat: true,
            },
        );
        this._setUseCommand(
            _t("Focus first page of previous group"),
            this._focusNextGroup.bind(this, "left"),
            "control+ArrowLeft",
        );
        this._setUseCommand(
            _t("Focus first page of next group"),
            this._focusNextGroup.bind(this, "right"),
            "control+ArrowRight",
        );
        this._setUseCommand(
            _t("Select focused page"),
            this._spaceKeySelect.bind(this),
            "control+space",
            {
                allowRepeat: true,
            },
        );
        this._setUseCommand(
            _t("Select/Deselect all pages"),
            this._selectAll.bind(this),
            "control+a",
        );
        this._setUseCommand(
            _t("Select previous page"),
            this._focusNextPage.bind(this, "left", true),
            "shift+ArrowLeft",
            {
                allowRepeat: true,
            },
        );
        this._setUseCommand(
            _t("Select next page"),
            this._focusNextPage.bind(this, "right", true),
            "shift+ArrowRight",
            {
                allowRepeat: true,
            },
        );
        this._setUseCommand(
            _t("Select previous pages of the group"),
            this._selectUntilSplit.bind(this, "left"),
            "control+shift+ArrowLeft",
        );
        this._setUseCommand(
            _t("Select next pages of the group"),
            this._selectUntilSplit.bind(this, "right"),
            "control+shift+ArrowRight",
        );
        this._setUseCommand(
            _t("Escape Preview/Deselect/Exit"),
            this._onPushExit.bind(this),
            "escape",
        );
        this._setUseCommand(
            _t("Split selected pages"),
            this._splitSelectionHandler.bind(this),
            "control+s",
            {
                allowRepeat: true,
            },
        );
        this._setUseCommand(
            _t("Split all white pages"),
            this._splitWhitePagesHandler.bind(this),
            "shift+s",
        );
        this._setUseCommand(
            _t("Delete focused or selected pages"),
            this.onArchive.bind(this),
            "alt+backspace",
        );
        useHotkey("ArrowDown", this._focusNextPage.bind(this, "down", false), {
            allowRepeat: true,
        });
        useHotkey("ArrowUp", this._focusNextPage.bind(this, "up", false), {
            allowRepeat: true,
        });
        useHotkey("shift+ArrowDown", this._focusNextPage.bind(this, "down", true), {
            allowRepeat: true,
        });
        useHotkey("shift+ArrowUp", this._focusNextPage.bind(this, "up", true), {
            allowRepeat: true,
        });
        useHotkey("enter", this._togglePreviewer.bind(this), {
            allowRepeat: true,
        });
        useHotkey("delete", this.onArchive.bind(this));
    }

    /**
     * @param {String} name
     * @param {Function} callback
     * @param {String} hotkey
     * @param {Object} options
     * @private
     */
    _setUseCommand(name, callback, hotkey, options) {
        useCommand(name, callback, {
            category: "smart_action",
            hotkey: hotkey,
            hotkeyOptions: options,
        });
    }

    /**
     * @return {String[]}
     */
    get ignoredPageIds() {
        return this.store.ignoredPageIds;
    }
    /**
     * @return {String[]}
     */
    get selectedPageIds() {
        return this.store.selectedPageIds;
    }
    /**
     * @return {Boolean}
     */
    get isDebugMode() {
        return Boolean(this.env.debug);
    }
    /**
     * @return {Boolean}
     */
    get allSelected() {
        return this.store.allSelected;
    }
    /**
     * @return {String[]}
     */
    get sortedPagesIds() {
        return this.store.sortedPageIds;
    }

    /**
     * @public
     * @param {String} groupId
     * @param {Boolean} toggle
     */
    onToggleEdit(groupId, toggle) {
        this.state.edit = toggle ? groupId : false;
    }
    /**
     * @public
     * @param {String} groupId
     */
    onClickGroupName(groupId) {
        this.store.toggleGroupSelection(groupId);
        this.store.focusedPage = undefined;
        this.onToggleEdit(groupId, true);
    }
    /**
     * @private
     */
    _computeCardsPerLine() {
        const allPages = [...document.querySelectorAll(".o_documents_pdf_page_frame")];
        if (!allPages.length) {
            return 1;
        }
        const top = allPages[0].getBoundingClientRect().top;
        return allPages.filter((page) => page.getBoundingClientRect().top === top)
            .length;
    }
    /**
     * @private
     */
    _unSelectPages() {
        this.store.unselectAll();
    }
    /**
     * @private
     */
    _splitSelectionHandler() {
        if (this.state.viewedPage) {
            return;
        }
        const selectedPages = this.selectedPageIds;
        const focusedPageisSelected = selectedPages.includes(this.store.focusedPage);
        const sortedPagesIds = this.sortedPagesIds;
        if (this.store.focusedPage && !focusedPageisSelected) {
            const indexPage = sortedPagesIds.indexOf(this.store.focusedPage);
            const previousPageId = sortedPagesIds[indexPage - 1];
            if (indexPage !== 0) {
                this.store.toggleSeparator(
                    previousPageId,
                    this.store.getPage(previousPageId).groupId,
                );
            }
            return;
        }
        let toggleSeparatorBool = true;
        const pagesToSplit = [];
        const pagesToGather = [];
        for (const pageId of selectedPages) {
            const indexPage = sortedPagesIds.indexOf(pageId);
            if (
                indexPage < sortedPagesIds.length - 1 &&
                this.store.getPage(sortedPagesIds[indexPage + 1]).isSelected
            ) {
                const isSeparatorActive = this.store.isLastPageOfGroup(pageId);
                toggleSeparatorBool = toggleSeparatorBool && isSeparatorActive;
                if (isSeparatorActive) {
                    pagesToGather.push(this.store.getPage(pageId));
                } else {
                    pagesToSplit.push(this.store.getPage(pageId));
                }
            }
        }
        const pagesToTreat = toggleSeparatorBool ? pagesToGather : pagesToSplit;
        for (const page of pagesToTreat) {
            this.store.toggleSeparator(page.pageId, page.groupId);
        }
    }
    async _splitWhitePagesHandler() {
        if (this.store.groupIds.length > 1) {
            this.dialog.add(ConfirmationDialog, {
                title: _t("Split on blank pages"),
                body: _t(
                    "This will discard the current grouping and rebuild the groups from the blank pages. This cannot be undone.",
                ),
                confirm: () => this._splitWhitePages(),
                cancel: () => {},
            });
            return;
        }
        await this._splitWhitePages();
    }
    /**
     * @private
     */
    async _splitWhitePages() {
        this.store.splitOnBlankPages({
            blankName: _t("Blank Page"),
            subDocName: (count) => _t("sub-doc-%s", count),
        });
    }
    /**
     * @private
     * @param {String} name
     * @param {Object} param1
     * @param {number} [param1.documentId]
     * @param {Object} [param1.file]
     * @param {String} [param1.url]
     */
    async _addFile(name, { documentId, file, url }) {
        let objectUrl;
        if (!url) {
            if (!file && !documentId) {
                return;
            }
            url = objectUrl = URL.createObjectURL(file);
            this._objectUrls.push(url);
        }
        const displayName = name;
        this.state.uploadingLock = true;
        const fileId = uniqueId("file");
        try {
            const pdf = await this._getPdf(url);

            if (file) {
                this._newFiles[fileId] = { type: "file", file };
            } else if (documentId) {
                this._newFiles[fileId] = { type: "document", documentId };
            }
            if (this._newFiles[fileId]) {
                this._newFiles[fileId].pdf = pdf;
                this._newFiles[fileId].objectUrl = objectUrl;
            }
            name = this._removePdfExtension(name || _t("New File"));

            const pageCount = pdf.numPages;
            const { pageIds, newPages } = this.store.createPagesForFile({
                fileId,
                name,
                pageCount,
                groupPerPage: this.props.documents.length <= 1,
            });
            for (const pageId of pageIds) {
                this.state.pageCanvases[pageId] = {};
            }
            this._newFiles[fileId].pageIds = this._newFiles[fileId].selectedPageIds =
                pageIds;
            this.state.uploadingLock = false;

            await this._loadCanvases({ newPages, pageCount, pdf });
        } catch (error) {
            this._displayErrorNotification(
                error?.name === "PasswordException"
                    ? _t("%s is password protected and cannot be split.", displayName)
                    : _t("Could not open %s.", displayName),
            );
            if (objectUrl) {
                URL.revokeObjectURL(objectUrl);
                this._objectUrls = this._objectUrls.filter(
                    (each) => each !== objectUrl,
                );
            }
        } finally {
            this.state.uploadingLock = false;
        }
    }
    /**
     * @private
     * @param {String} message
     */
    _displayErrorNotification(message) {
        this.notification.add(message, {
            type: "danger",
        });
    }
    /**
     * @private
     * @param {number} number
     */
    _displayNumberCreatedDocuments(number) {
        this.notification.add(_t("%s new document(s) created", number), {
            type: "success",
        });
    }
    /**
     * @private
     * @param {number} number
     */
    _displayNumberDeletedPages(number) {
        this.notification.add(_t("%s page(s) deleted", number), { type: "success" });
    }
    /**
     * @private
     * @param {number} [actionId]
     */
    async _applyChanges(actionId) {
        let processedPageIds = this.selectedPageIds;
        let pageIds = this.ignoredPageIds;
        if (processedPageIds.length === 0 && !this.store.focusedPage) {
            this._displayErrorNotification(_t("No document has been selected"));
            return;
        }
        if (processedPageIds.length === 0) {
            processedPageIds = [this.store.focusedPage];
            pageIds = pageIds.filter((pageId) => pageId !== this.store.focusedPage);
        }
        const exit = !pageIds.length;

        let fileName = _t("Remaining Pages");
        if (this.state.fileName) {
            fileName = this.state.fileName + " " + fileName;
        }
        try {
            const documentIds = await this._sendChanges();
            await this.props.onProcessDocuments({ documentIds, actionId, exit });
            this._displayNumberCreatedDocuments(documentIds.length);
            if (!exit) {
                this._embeddedActionApplied = true;
                for (const pageId of processedPageIds) {
                    this._removePage(pageId, { fromFile: true });
                }
            } else {
                this.props.close();
            }
        } catch (error) {
            this._displayErrorNotification(error.message || error);
            if (pageIds.length) {
                this.store.createGroup({ name: fileName, pageIds, isSelected: true });
            }
        } finally {
            this.state.uploadingLock = false;
        }
    }

    async _isBlankPage(page, canvas) {
        const pageContent = await page.getTextContent();
        const hasText = pageContent.items.length > 0;
        return !hasText && this._hasBlankGraphics(canvas);
    }

    _hasBlankGraphics(canvas) {
        const pixels = canvas
            .getContext("2d")
            .getImageData(0, 0, canvas.width, canvas.height, {
                colorSpace: "display-p3",
            }).data;
        let totalSum = 0;
        for (let i = 0; i < pixels.length; i += 4) {
            for (let channel = 0; channel < 3; channel++) {
                const value = pixels[i + channel];
                if (value < BLANK_PIXEL_FILTER_VALUE) {
                    totalSum += 255 - value;
                    if (totalSum >= BLANK_PAGE_THRESHOLD) {
                        return false;
                    }
                }
            }
        }
        return true;
    }

    /**
     * @private
     * @param {String} url
     * @return {PdfJsObject}
     */
    async _getPdf(url) {
        const pdf = await pdfjsLib.getDocument(url).promise;
        this._pdfDocuments.push(pdf);
        return pdf;
    }
    /**
     * @private
     */
    async _loadAssets() {
        await loadPDFJS();
    }
    /**
     * @private
     * @param {Object} [param0]
     * @param {Object} [param0.newPages]
     * @param {number} [param0.pageCount]
     * @param {PdfjsObject} [param0.pdf]
     */
    async _loadCanvases({ newPages, pageCount, pdf }) {
        for (let pageNumber = 1; pageNumber <= pageCount; pageNumber++) {
            if (!this.root.el) {
                break;
            }
            const pageId = newPages[pageNumber];
            const page = await pdf.getPage(pageNumber);
            const canvas = await this._renderCanvas(toRaw(page), {
                width: 160,
                height: 230,
            });
            this.state.pageCanvases[pageId] = { page, canvas };
            const storePage = this.store.getPage(pageId);
            if (storePage) {
                storePage.isBlank = await this._isBlankPage(page, canvas);
            }
        }
    }
    /**
     * @private
     * @param {Object} page
     * @param {Object} param1
     * @param {number} param1.width
     * @param {number} param1.height
     * @return {DomElement}
     */
    async _renderCanvas(page, { width, height }) {
        const viewPort = page.getViewport({ scale: 1 });
        const isLandscape = viewPort.width > viewPort.height;
        const canvas = document.createElement("canvas");
        canvas.className = "o_documents_pdf_canvas";
        canvas.width = width;
        canvas.height = height;
        const scale = isLandscape
            ? Math.min(canvas.width / viewPort.height, canvas.height / viewPort.width)
            : Math.min(canvas.width / viewPort.width, canvas.height / viewPort.height);
        await page.render({
            canvasContext: canvas.getContext("2d"),
            viewport: page.getViewport({
                scale,
                rotation: isLandscape ? 270 : viewPort.rotation,
            }),
        }).promise;
        return canvas;
    }
    /**
     * @private
     */
    async _sendChanges() {
        this.state.uploadingLock = true;
        const fileIds = [];
        const files = [];
        for (const key in this._newFiles) {
            if (this._newFiles[key].type === "file") {
                files.push(this._newFiles[key].file);
                fileIds.push(key);
            }
        }
        const fileGroups = Object.values(
            JSON.parse(JSON.stringify(this.store.groupData)),
        );
        let activePages = this.selectedPageIds;
        if (!activePages.length) {
            activePages = this.store.focusedPage ? [this.store.focusedPage] : [];
            this.store.focusedPage = false;
        }
        for (const group of fileGroups) {
            group.pageIds = group.pageIds.filter((page) => activePages.includes(page));
        }
        const newFiles = fileGroups.filter((group) => group.pageIds.length > 0);
        for (const newFile of newFiles) {
            newFile.new_pages = [];
            for (const pageId of newFile.pageIds) {
                const page = this.store.getPage(pageId);
                const file = this._newFiles[page.fileId];
                const old_file_type = file.type;
                const old_file_index =
                    old_file_type === "file"
                        ? fileIds.indexOf(page.fileId)
                        : file.documentId;
                newFile.new_pages.push({
                    old_file_type,
                    old_file_index,
                    old_page_number: page.localPageNumber,
                });
            }
            delete newFile.pageIds;
        }
        newFiles.reverse();
        const sourceDocument = this.props.documents[0];
        const data = new FormData();
        data.append("csrf_token", odoo.csrf_token);
        for (const file of files) {
            data.append("ufile", file);
        }
        data.append("new_files", JSON.stringify(newFiles));
        data.append("archive", this.state.archive);
        data.append(
            "vals",
            JSON.stringify({
                folder_id: sourceDocument.folder_id?.id ?? false,
                tag_ids: sourceDocument.tag_ids.currentIds,
                owner_id: sourceDocument.owner_id.id,
                partner_id: sourceDocument.partner_id.id,
                active: this.state.keepDocument,
            }),
        );
        const response = await fetch("/documents/pdf_split", {
            method: "post",
            body: data,
        });
        if (!response.ok) {
            throw new Error(_t("PDF split failed (status %s).", response.status));
        }
        return response.json();
    }
    /**
     * @private
     * @param {String} pageId
     * @param {Object} [param1]
     * @param {boolean} [param1.fromFile]
     */
    _removePage(pageId, { fromFile } = {}) {
        const page = this.store.getPage(pageId);
        if (!page) {
            return;
        }
        this.store.removePage(pageId);
        if (fromFile && page.fileId && this._newFiles[page.fileId]) {
            const selectedPageIds = this._newFiles[page.fileId].selectedPageIds;
            this._newFiles[page.fileId].selectedPageIds = selectedPageIds.filter(
                (number) => number !== pageId,
            );
            if (this._newFiles[page.fileId].selectedPageIds.length === 0) {
                this._removeFile(page.fileId);
            } else {
                delete this.state.pageCanvases[pageId];
            }
            page.fileId = false;
        }
    }
    /**
     * @private
     * @param {String} fileId
     */
    _removeFile(fileId) {
        const fileData = this._newFiles[fileId];
        if (!fileData) {
            return;
        }
        for (const pageId of fileData.pageIds || []) {
            delete this.state.pageCanvases[pageId];
            this.store.deletePage(pageId);
        }
        if (fileData.pdf) {
            fileData.pdf.destroy();
            this._pdfDocuments = this._pdfDocuments.filter(
                (pdf) => pdf !== fileData.pdf,
            );
        }
        if (fileData.objectUrl) {
            URL.revokeObjectURL(fileData.objectUrl);
            this._objectUrls = this._objectUrls.filter(
                (url) => url !== fileData.objectUrl,
            );
        }
        delete this._newFiles[fileId];
    }
    /**
     * @private
     * @param {String} name
     */
    _removePdfExtension(name) {
        return name.replace(/\.pdf$/gi, "");
    }
    /**
     * @private
     */
    _exitSplitTools(formerTargetCallback = () => {}) {
        this.dialog.add(ExitSplitToolsDialog, {
            isEmbeddedActionApplied: this._embeddedActionApplied,
            onDeleteRemainingPages: async () => {
                await this.props.close();
                formerTargetCallback();
            },
            onGatherRemainingPages: async () => {
                await this._exitByGatheringRemainingPages();
                formerTargetCallback();
            },
            close: () => {},
        });
    }
    /**
     * @private
     */
    async _exitByGatheringRemainingPages() {
        this.store.regroupAll({
            name: this.state.fileName
                ? _t("%s (remaining pages)", this.state.fileName)
                : _t("Remaining Pages"),
            isSelected: true,
        });
        await this._applyChanges();
    }
    /**
     * @private
     */
    _keepFocusedPageInScreen() {
        if (!this.store.focusedPage || !this.pageViewer.el) {
            return;
        }
        const card = document.querySelector(
            `[data-id="${CSS.escape(this.store.focusedPage)}"]`,
        );
        if (!card) {
            return;
        }
        const focusedCardCoordinates = card.getBoundingClientRect();
        const pageViewerCoordinates = this.pageViewer.el.getBoundingClientRect();
        const bottomDifference =
            focusedCardCoordinates.bottom - pageViewerCoordinates.bottom;
        const topDifference = focusedCardCoordinates.top - pageViewerCoordinates.top;
        if (bottomDifference > 0) {
            this.pageViewer.el.scrollBy(0, bottomDifference + 60);
        }
        if (topDifference < 0) {
            this.pageViewer.el.scrollBy(0, topDifference - 10);
        }
    }

    /**
     * @private
     * @param {Event} ev
     */
    _onShiftDown(ev) {
        if (document.activeElement.classList.contains("o_pdf_name_input")) {
            return;
        }
        if (
            ev.key === "Shift" &&
            !ev.metaKey &&
            !ev.ctrlKey &&
            !ev.altKey &&
            !this.state.viewedPage &&
            this.store.focusedPage
        ) {
            this.store.toggleSelected(this.store.focusedPage);
        }
    }
    /**
     * @private
     * @param {String} direction
     * @param {Boolean} doSelect
     */
    _focusNextPage(direction, doSelect) {
        if (this.state.viewedPage) {
            if (direction === "left") {
                this.onClickPrevious();
            }
            if (direction === "right") {
                this.onClickNext();
            }
            return;
        }
        this.store.focusNextPage(direction, doSelect, () =>
            this._computeCardsPerLine(),
        );
        this._keepFocusedPageInScreen();
    }
    /**
     * @private
     * @param {String} direction
     */
    _focusNextGroup(direction) {
        if (this.state.viewedPage) {
            return;
        }
        this.store.focusNextGroup(direction);
        this._keepFocusedPageInScreen();
    }
    /**
     * @private
     */
    _togglePreviewer() {
        if (this.store.focusedPage && !this.state.viewedPage) {
            this.onClickPage(this.store.focusedPage);
        }
        if (this.store.focusedPage && this.state.viewedPage) {
            this._onPushExit();
        }
    }
    /**
     * @private
     */
    _spaceKeySelect() {
        if (this.store.focusedPage && !this.state.viewedPage) {
            this.store.toggleSelected(this.store.focusedPage);
        }
    }
    /**
     * @private
     * @param {String} direction
     */
    _selectUntilSplit(direction) {
        if (this.state.viewedPage) {
            return;
        }
        this.store.selectUntilSplit(direction);
    }
    /**
     * @private
     */
    _selectAll() {
        if (this.state.viewedPage) {
            return;
        }
        this.store.toggleSelectAll();
    }
    /**
     * @private
     */
    _onPushExit() {
        if (this.state.viewedPage) {
            this.store.focusedPage = this.state.viewedPage;
            this.previewCanvas = undefined;
            this.state.viewedPage = undefined;
            return;
        }
        if (this.selectedPageIds.length) {
            this._unSelectPages();
            return;
        }
        if (this.store.focusedPage) {
            this.store.focusedPage = undefined;
            return;
        }
        this._exitSplitTools();
    }

    /**
     * @private
     * @param {Event} ev
     */
    _onMouseDown(ev) {
        if (
            ev.target.closest(".o_pdf_page") ||
            ev.target.closest(".o_page_splitter_wrapper") ||
            ev.target.closest(".o_documents_pdf_manager_top_bar") ||
            ev.target.closest(".o_main_navbar") ||
            ev.target.closest(".o_documents_pdf_page_preview") ||
            ev.target.closest(".o_pdf_group_name_block") ||
            ev.button !== 0
        ) {
            return;
        }
        this._selectionX = ev.pageX;
        this._selectionY = ev.pageY - 40;
        this._selectionScrollTop = this.pageViewer.el.scrollTop;
        this._selectionScrollLeft = this.pageViewer.el.scrollLeft;
        this.state.selectionBoxArgs["left"] = this._selectionX + "px";
        this.state.selectionBoxArgs["top"] = this._selectionY + "px";
        this.state.selectionBoxArgs["width"] = 0 + "px";
        this.state.selectionBoxArgs["height"] = 0 + "px";
        this.state.isSelecting = true;
        if (!ev.ctrlKey && !ev.metaKey && !ev.shiftKey) {
            if (!this.selectedPageIds.length) {
                this.store.focusedPage = undefined;
            }
            this.state.edit = false;
            this._unSelectPages();
        }
    }
    /**
     * @private
     * @param {Event} ev
     */
    _onMouseMove(ev) {
        if (!this.state.isSelecting) {
            return;
        }
        this.store.focusedPage = false;
        const x = ev.pageX;
        const y = ev.pageY - 40;
        const scrollTopDiff = this.pageViewer.el.scrollTop - this._selectionScrollTop;
        const scrollLeftDiff =
            this.pageViewer.el.scrollLeft - this._selectionScrollLeft;
        this.state.selectionBoxArgs["left"] =
            x - this._selectionX + scrollLeftDiff < 0
                ? x + "px"
                : this._selectionX - scrollLeftDiff + "px";
        this.state.selectionBoxArgs["top"] =
            y - this._selectionY + scrollTopDiff < 0
                ? y + "px"
                : this._selectionY - scrollTopDiff + "px";
        this.state.selectionBoxArgs["width"] =
            Math.abs(x - (this._selectionX - scrollLeftDiff)) + "px";
        this.state.selectionBoxArgs["height"] =
            Math.abs(y - (this._selectionY - scrollTopDiff)) + "px";

        const boxCoordinates = this.selectionBox.el.getBoundingClientRect();
        const boxTop = boxCoordinates.top;
        const boxBottom = boxTop + boxCoordinates.height;
        const boxLeft = boxCoordinates.left;
        const boxRight = boxLeft + boxCoordinates.width;
        const cards = this.pageViewer.el.querySelectorAll(".o_pdf_page");
        for (const card of cards) {
            const cardCoordinates = card.getBoundingClientRect();
            const cardTop = cardCoordinates.top;
            const cardBottom = cardTop + cardCoordinates.height;
            const cardLeft = cardCoordinates.left;
            const cardRight = cardLeft + cardCoordinates.width;

            if (
                boxLeft < cardRight &&
                boxRight > cardLeft &&
                boxTop < cardBottom &&
                boxBottom > cardTop
            ) {
                this.store.setSelected(card.dataset.id, !ev.shiftKey);
            } else if (!ev.metaKey && !ev.ctrlKey && !ev.shiftKey) {
                this.store.setSelected(card.dataset.id, false);
            }
        }
    }
    /**
     * @private
     */
    _onMouseUp() {
        this.state.isSelecting = false;
    }
    /**
     * @public
     * @param {number} actionId
     */
    onClickEmbeddedAction(actionId) {
        this._applyChanges(actionId);
    }
    /**
     * @public
     */
    onClickSplit() {
        this.state.keepDocument = true;
        this._applyChanges();
    }
    /**
     * @public
     * @param {MouseEvent} ev
     */
    onClickArchive(ev) {
        ev.target.blur();
        this.state.archive = !this.state.archive;
    }
    /**
     * @public
     */
    onClickGlobalAdd() {
        this.addFileInput.el.click();
    }
    /**
     * @public
     */
    async onArchive() {
        let pagesToDelete = this.selectedPageIds;
        if (
            pagesToDelete.length === 0 &&
            !this.store.focusedPage &&
            !this.state.viewedPage
        ) {
            this._displayErrorNotification(_t("No document has been selected"));
            return;
        }
        const sortedPagesIds = this.sortedPagesIds;
        let messageInput = _t(
            "Are you sure that you want to delete the selected page(s)",
        );
        let nextFocusedPageId = pagesToDelete.includes(this.store.focusedPage)
            ? false
            : this.store.focusedPage;
        if (
            pagesToDelete.length === 0 ||
            this.state.viewedPage ||
            (this.store.focusedPage && !pagesToDelete.includes(this.store.focusedPage))
        ) {
            pagesToDelete = [this.store.focusedPage];
            messageInput = this.state.viewedPage
                ? _t("Are you sure that you want to delete this page ?")
                : _t("Are you sure that you want to delete the focused page ?");
            const focusedPageIndex = sortedPagesIds.indexOf(this.store.focusedPage);
            if (focusedPageIndex + 1 < sortedPagesIds.length) {
                nextFocusedPageId = sortedPagesIds[focusedPageIndex + 1];
            } else if (focusedPageIndex - 1 >= 0) {
                nextFocusedPageId = sortedPagesIds[focusedPageIndex - 1];
            } else {
                nextFocusedPageId = undefined;
            }
        }
        this.dialog.add(ConfirmationDialog, {
            body: messageInput,
            confirm: async () => {
                for (const pageId of pagesToDelete) {
                    this._removePage(pageId, { fromFile: true });
                }
                if (this.store.numberOfPages === 0) {
                    await this.props.onProcessDocuments({ isForcingDelete: true });
                    await this.props.close();
                }
                this._displayNumberDeletedPages(pagesToDelete.length);
                this.store.focusedPage = nextFocusedPageId;
                if (this.state.viewedPage && nextFocusedPageId) {
                    await this.onClickPage(nextFocusedPageId);
                } else {
                    this.state.viewedPage = undefined;
                }
            },
            cancel: () => {},
        });
    }
    /**
     * @public
     * @param {MouseEvent} ev
     */
    async onFileInputChange(ev) {
        this.state.fileName = "";
        if (!ev.target.files.length) {
            return;
        }
        const files = ev.target.files;
        for (const file of files) {
            await this._addFile(file.name, { file });
        }
        ev.target.value = null;
    }
    /**
     * @public
     */
    onClickExit() {
        this._exitSplitTools();
    }
    /**
     * @private
     * @param {HTMLElement} target
     * @returns {boolean}
     */
    _isLeavingClick(target) {
        if (target.closest(".o_burger_menu_content")) {
            return true;
        }
        const menuItem = target.closest(".dropdown-item");
        if (!menuItem && !target.closest(".o_menu_toggle")) {
            return false;
        }
        if (NON_LEAVING_MENUS.includes(menuItem?.dataset.menu)) {
            return false;
        }
        return !target.closest("[data-dropdown-is-mobile]");
    }
    /**
     * @private
     * @param {Event} ev
     */
    _onOutsideClick(ev) {
        if (this._exitSplitToolsClick || !this._isLeavingClick(ev.target)) {
            return;
        }
        ev.stopPropagation();
        ev.preventDefault();
        this._exitSplitTools(() => {
            this._exitSplitToolsClick = true;
            ev.target.click();
            this._exitSplitToolsClick = false;
        });
    }
    /**
     * @public
     * @param {String} pageId
     */
    async onClickPage(pageId) {
        this.store.focusedPage = pageId;
        const page = this.state.pageCanvases[pageId].page;
        if (!page) {
            return;
        }
        const ratio = 18 / 13;
        const width = this.pagePreview.el.clientWidth - (30 * window.innerWidth) / 100;
        this.previewCanvas = await this._renderCanvas(toRaw(page), {
            width: width,
            height: width * ratio,
        });
        this.state.viewedPage = pageId;
        const targetGroup = this.store.getGroupOfPage(pageId);
        this.state.viewedPageName =
            targetGroup.name + "-p" + (targetGroup.pageIds.indexOf(pageId) + 1);
        const sortedPagesIds = this.sortedPagesIds;
        this.state.viewedPageIndex = sortedPagesIds.indexOf(pageId);
    }
    /**
     * @public
     */
    async onClickPrevious() {
        if (this.state.viewedPageIndex > 0) {
            await this.onClickPage(this.sortedPagesIds[this.state.viewedPageIndex - 1]);
        }
    }
    /**
     * @public
     */
    async onClickNext() {
        if (this.state.viewedPageIndex < this.store.numberOfPages - 1) {
            await this.onClickPage(this.sortedPagesIds[this.state.viewedPageIndex + 1]);
        }
    }
    /**
     * @public
     * @param {customEvent} ev
     */
    onClickExitPreview(ev) {
        if (
            ev.target.classList.contains("o_documents_pdf_page_preview") ||
            ev.target.closest(".o_close_button")
        ) {
            this.store.focusedPage = this.state.viewedPage;
            this.previewCanvas = undefined;
            this.state.viewedPage = undefined;
        }
    }
    /**
     * @public
     * @param {String} pageId
     * @param {Boolean} isRangeSelection
     */
    onSelectClicked(pageId, isRangeSelection) {
        this.store.clickSelect(pageId, { isRangeSelection });
    }
    /**
     * @public
     * @param {String} pageId
     * @param {String} groupId
     */
    onClickPageSeparator(pageId, groupId) {
        this.store.toggleSeparator(pageId, groupId);
    }
    /**
     * @public
     * @param {String} groupId
     * @param {String} name
     */
    onEditName(groupId, name) {
        this.store.renameGroup(groupId, name);
    }
    /**
     * @public
     * @param {customEvent} ev
     */
    onPageDragStart(ev) {
        ev.stopPropagation();
    }
    /**
     * @public
     * @param {String} ev.detail.targetPageId
     * @param {String} ev.detail.pageId
     */
    onPageDrop(targetPageId, pageId) {
        this.store.movePage(pageId, targetPageId);
    }
}
