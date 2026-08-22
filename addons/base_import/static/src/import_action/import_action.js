/** @odoo-module native */
import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { useDropzone } from "@web/components/dropzone";
import { FileInput } from "@web/components/file_input";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useFileUploader } from "@web/core/utils/files";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";
import { DocumentationLink } from "@web/views/widgets";
import { standardActionServiceProps } from "@web/webclient/actions";

import { ImportDataContent } from "../import_data_content/import_data_content.js";
import { ImportDataProgress } from "../import_data_progress/import_data_progress.js";
import { ImportDataSidepanel } from "../import_data_sidepanel/import_data_sidepanel.js";
import { useImportModel } from "../import_model.js";

export class ImportAction extends Component {
    static template = "ImportAction";
    static nextId = 1;
    static components = {
        FileInput,
        ImportDataContent,
        ImportDataSidepanel,
        Layout,
        DocumentationLink,
    };
    static props = { ...standardActionServiceProps };
    static path = "import";
    static displayName = _t("Import a File");
    // Single source of truth for both the FileInput button (import_action.xml)
    // and the dropzone validation below: they used to disagree (button allowed
    // .xls/.xlsm/.ods too, dropzone only .csv/.xlsx and rejected the rest with
    // two different, both-incomplete error messages) (t24068 F6-frontend).
    static ACCEPTED_FILE_EXTENSIONS = [".csv", ".xls", ".xlsx", ".xlsm", ".ods"];

    setup() {
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.env.config.setDisplayName(this.props.action.name || _t("Import a File"));
        this.model = useImportModel({
            env: this.env,
            context: this.props.action.params?.context || {},
        });

        this.state = useState({
            filename: undefined,
            numRows: 0,
            importMessages: [],
            importProgress: {
                value: 0,
                step: 1,
            },
            isPaused: false,
            isTested: false,
            isImporting: false,
            previewError: "",
        });

        this.uploadFiles = useFileUploader();
        useDropzone(useRef("root"), async (event) => {
            const { files } = event.dataTransfer;
            if (files.length === 0) {
                this.notification.add(this.invalidFileMessage, { type: "danger" });
            } else if (files.length > 1) {
                this.notification.add(_t("Please upload a single file."), {
                    type: "danger",
                });
            } else {
                const file = files[0];
                // Same accepted-extension list as the FileInput button
                // (import_action.xml) — used to only accept .csv/.xlsx here,
                // silently rejecting valid .xls/.xlsm/.ods drops that the
                // button accepted fine (t24068 F6-frontend).
                const isValidFile = ImportAction.ACCEPTED_FILE_EXTENSIONS.some((ext) =>
                    file.name.toLowerCase().endsWith(ext)
                );
                if (!isValidFile) {
                    this.notification.add(this.invalidFileMessage, { type: "danger" });
                } else {
                    await this.uploadFiles(this.uploadFilesRoute, {
                        csrf_token: odoo.csrf_token,
                        ufile: [file],
                        model: this.resModel,
                        id: this.model.id,
                    });
                    this.handleFilesUpload([file]);
                }
            }
        });

        onWillStart(this.onWillStart);
    }

    /**
     * The window action this import was opened on top of, if any.
     *
     * Read off `controllerStack` — and, on a deep link, the URL `actionStack`
     * — both of which the action service declares as its public surface. This
     * used to read `actionService.currentAction` and
     * `actionService.currentController` — neither of which exists: the web
     * architecture redesign made them the private `_getCurrentAction()` /
     * `_getCurrentController()` and did not carry this consumer across. The
     * damage was quiet, because `await undefined` is `undefined` rather than a
     * crash: opening the import screen from a URL bounced straight back out
     * via `historyBack()`, and opening it from a list view lost the origin
     * action, so "Imported records" fell back to a default `list,form` instead
     * of the views the user was actually looking at.
     *
     * @returns {object | null}
     */
    async _getOriginAction() {
        const stack = this.actionService.controllerStack ?? [];
        // This client action is itself on the stack by the time we run, so walk
        // down to the nearest window action rather than taking the top. Read
        // `_originalAction`, not the controller's live `action`: the latter is
        // the processed runtime copy, whose `views`/`view_mode` no longer match
        // what the user's own action declared — and those two fields are the
        // whole reason we want it (see `openRecords`).
        for (let i = stack.length - 1; i >= 0; i--) {
            const controller = stack[i];
            if (controller?.action?.type !== "ir.actions.act_window") {
                continue;
            }
            const original = JSON.parse(controller.action._originalAction || "null");
            return original ?? controller.action;
        }

        // Deep link, e.g. /odoo/action-2/import: the web client mounts this
        // client action while restoring URL state, so nothing is on the
        // controller stack yet and the action beneath us exists only as an id
        // in `actionStack`. Resolve it — otherwise the import screen has no
        // model to import into and bounces straight back out.
        const urlStack = this.props.action.params?.actionStack ?? [];
        const selfIndex = urlStack.findIndex(
            (entry) => entry?.action === ImportAction.path
        );
        const preceding = selfIndex === -1 ? urlStack : urlStack.slice(0, selfIndex);
        for (let i = preceding.length - 1; i >= 0; i--) {
            const actionId = preceding[i]?.action;
            if (actionId === undefined || actionId === null) {
                continue;
            }
            try {
                const action = await this.actionService._loadAction(actionId);
                if (action?.type === "ir.actions.act_window") {
                    return action;
                }
            } catch {
                // A stale or deleted action in the URL is not this screen's
                // problem to report; keep looking further down the stack.
            }
        }
        return null;
    }

    async onWillStart() {
        // this.props.action.params.model is there for retro-compatibility issues
        const activeModel =
            this.props.action.params?.model || this.props.action.params?.active_model;
        const originAction = await this._getOriginAction();
        if (activeModel) {
            this.resModel = activeModel;
            if (originAction?.res_model === this.resModel) {
                this.action = originAction;
            } else {
                this.props.updateActionState({ active_model: this.resModel });
            }
        } else if (originAction) {
            this.action = originAction;
            this.resModel = originAction.res_model;
        } else {
            // Nothing tells us what to import into — a bare /odoo/import URL,
            // or an import opened over a non-window action. Leave rather than
            // mount an action that cannot work.
            return this.env.config.historyBack();
        }
        this.model.setResModel(this.resModel);
        return this.model.init();
    }

    cancel() {
        this.env.config.historyBack();
    }

    openRecords(resIds) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: _t("Imported records"),
            res_model: this.model.resModel,
            view_mode: this.action?.view_mode || "list,form",
            views: this.action?.views || [
                [false, "list"],
                [false, "form"],
            ],
            domain: [["id", "in", resIds]],
            target: "current",
            path: "imported-records",
        });
    }

    get display() {
        return {
            controlPanel: {},
        };
    }

    get importTemplates() {
        return this.model.importTemplates;
    }

    get uploadFilesRoute() {
        return "/base_import/set_file";
    }

    get acceptedFileExtensions() {
        return ImportAction.ACCEPTED_FILE_EXTENSIONS.join(", ");
    }

    get invalidFileMessage() {
        return _t("Please upload a valid file to import (%(extensions)s).", {
            extensions: this.acceptedFileExtensions,
        });
    }

    //--------------------------------------------------------------------------
    // Options
    //--------------------------------------------------------------------------

    get formattingOptions() {
        return this.model.formattingOptions;
    }

    get totalToImport() {
        return this.state.numRows - parseInt(this.importOptions.skip);
    }

    get totalSteps() {
        return this.isBatched ? Math.ceil(this.totalToImport / this.importOptions.limit) : 1;
    }

    get importOptions() {
        return this.model.importOptions;
    }

    get isPreviewing() {
        return this.state.filename !== undefined;
    }

    // Activate the batch configuration panel only if the number of rows > 100. (In order to let the user choose
    // the batch size even for medium size file. Could be useful to reduce the batch size for complex models).
    get isBatched() {
        return this.state.numRows > 100;
    }

    async onOptionChanged(name, value, fieldName = null) {
        this.model.block();
        const result = await this.model.setOption(name, value, fieldName);
        if (result) {
            const { res, error } = result;
            if (!error && res.num_rows) {
                this.state.numRows = res.num_rows;
                this.state.previewError = undefined;
            } else {
                this.state.previewError = error;
            }
        }
        this.model.unblock();
    }

    async reload() {
        this.model.block();
        await this.model.updateData();
        this.model.unblock();
    }

    //--------------------------------------------------------------------------
    // File
    //--------------------------------------------------------------------------

    async handleFilesUpload(files) {
        if (!files || files.length <= 0) {
            return;
        }

        this.state.filename = files[0].name;
        this.state.importMessages = [];

        this.model.block(_t("Loading file..."));
        const { res, error } = await this.model.updateData(true);

        if (error) {
            this.state.previewError = error;
        } else {
            this.state.numRows = res.num_rows;
            this.state.previewError = undefined;
        }
        this.state.isTested = false;
        this.model.unblock();
    }

    async handleImport(isTest = true) {
        // `model.block()` paints the overlay asynchronously (next frame), so it
        // alone doesn't stop a double-click firing two concurrent
        // execute_import calls within the same frame (duplicate-import risk,
        // t24068 F4-frontend). This flag is set synchronously, before any
        // `await`.
        if (this.state.isImporting) {
            return;
        }
        this.state.isImporting = true;

        const message = isTest ? _t("Testing") : _t("Importing");

        let blockComponent;
        if (this.isBatched) {
            blockComponent = {
                class: ImportDataProgress,
                props: {
                    stopImport: () => this.stopImport(),
                    totalSteps: this.totalSteps,
                    importProgress: this.state.importProgress,
                },
            };
        }

        this.model.block(message, blockComponent);

        let res = { ids: [] };
        try {
            const data = await this.model.executeImport(
                isTest,
                this.totalSteps,
                this.state.importProgress
            );
            res = data.res;
        } finally {
            this.model.unblock();
            this.state.isImporting = false;
        }

        if (!isTest && res.nextrow) {
            this.state.isPaused = true;
        }

        if (res.ids.length) {
            if (!isTest) {
                if (res.hasError) {
                    return;
                }
                this.notification.add(_t("%s records successfully imported", res.ids.length), {
                    type: "success",
                });
                if (!this.state.isPaused) {
                    this.openRecords(res.ids);
                }
            } else {
                this.state.isTested = true;
            }
        }
    }

    stopImport() {
        this.model.stopImport();
    }

    //--------------------------------------------------------------------------
    // Fields
    //--------------------------------------------------------------------------

    onFieldChanged(column, fieldInfo) {
        this.model.setColumnField(column, fieldInfo);
    }

    isFieldSet(column) {
        return column.fieldInfo != null;
    }

    get hasBinaryFields() {
        return this.model.columns.some((column) => column.fieldInfo?.type === "binary");
    }
}

registry.category("actions").add("import", ImportAction);
