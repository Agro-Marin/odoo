/** @odoo-module native */
import {
    Component,
    onWillStart,
    onWillUnmount,
    reactive,
    useRef,
    useState,
} from "@odoo/owl";
import { CodeEditor } from "@web/components/code_editor";
import { CheckboxItem, Dropdown, DropdownItem } from "@web/components/dropdown";
import { SelectMenu } from "@web/components/select_menu";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { rpc } from "@web/core/network";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { sortBy } from "@web/core/utils/collections/arrays";
import { KeepLast } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/ui/dialog";

import { ResourceEditorWarningOverlay } from "./resource_editor_warning.js";
import { checkSCSS, checkXML, formatXML } from "./utils.js";

const BUNDLES_RESTRICTION = [
    "web.assets_frontend",
    "web.assets_frontend_minimal",
    "web.assets_frontend_lazy",
];

const log = makeLogger("website.component.resource_editor");

export class ResourceEditor extends Component {
    static components = {
        ResourceEditorWarningOverlay,
        CodeEditor,
        Dropdown,
        CheckboxItem,
        DropdownItem,
        SelectMenu,
    };
    static template = "website.ResourceEditor";
    static props = {
        close: { type: Function, optional: true },
    };
    static defaultProps = {
        close: () => {},
    };

    setup() {
        useLifecycleLog(log);
        this.website = useService("website");
        this.orm = useService("orm");
        this.dialog = useService("dialog");

        this.keepLast = new KeepLast();

        this.editorRef = useRef("editor");

        this.debug = this.env.debug;
        this.viewKey =
            this.website.pageDocument &&
            this.website.pageDocument.documentElement.dataset.viewXmlid;

        this.types = {
            xml: "XML (HTML)",
            scss: "SCSS (CSS)",
            js: "JS",
        };
        this.typeToCodeEditorModeMap = {
            xml: "qweb",
            scss: "scss",
            js: "javascript",
        };

        this.xmlFilters = {
            views: _t("Only Views"),
            all: _t("Views and Assets bundles"),
        };
        this.scssFilters = {
            custom: _t("Only Custom SCSS Files"),
            restricted: _t("Only Page SCSS Files"),
            all: _t("All SCSS Files"),
        };
        this.state = useState({
            type: "xml",
            xmlFilter: "views",
            scssFilter: "custom",
            currentResource: false,
            showEditWarning: true,
            resources: {
                xml: {},
                js: {},
                scss: {},
            },
            sortedXML: [],
            sortedSCSS: [],
            sortedJS: [],
            saving: false,
        });

        let showErrorInterval;
        this.errors = reactive([], () => {
            clearInterval(showErrorInterval);
            if (this.errors.length) {
                log.lifecycle("error highlight interval started", () => ({
                    errors: this.errors.length,
                }));
                this.showErrorLine();
                showErrorInterval = setInterval(() => this.showErrorLine(), 500);
            } else {
                log.lifecycle("errors cleared: interval stopped");
                this.clearErrorLine();
            }
        });
        onWillUnmount(() => clearInterval(showErrorInterval));

        onWillStart(async () => this.loadResources());
    }

    get context() {
        return {
            ...user.context,
            website_id: this.website.currentWebsite.id,
        };
    }

    get resourceInfo() {
        if (!this.state.currentResource) {
            return "";
        }
        if (this.state.type === "xml") {
            return _t("Template ID: %s", this.state.currentResource.key);
        } else if (this.state.type === "scss") {
            return _t("SCSS file: %s", this.state.currentResource.url);
        } else {
            return _t("JS file: %s", this.state.currentResource.url);
        }
    }

    get selectMenuProps() {
        const props = {
            onSelect: (value) => {
                this.state.currentResource =
                    this.state.resources[this.state.type][value];
            },
            autoSort: false,
            required: true,
        };
        if (this.state.type === "xml") {
            const choices = this.state.sortedXML.map((view) => ({
                value: view.id,
                label: view.label,
            }));
            const value = this.state.currentResource?.id;
            return { ...props, choices, value };
        } else {
            const { type, sortedSCSS, sortedJS } = this.state;
            const bundles = type === "scss" ? sortedSCSS : sortedJS;
            const groups = bundles.map(([name, files]) => {
                const choices = files.map((file) => ({
                    value: file.url,
                    label: file.label,
                }));
                return { label: name, choices };
            });
            const value = this.state.currentResource?.url;
            return { ...props, groups, value };
        }
    }

    /**
     * @param {string} url
     * @returns {boolean}
     */
    isCustomResource(url) {
        if (this.state.type === "scss") {
            return this.state.resources.scss[url].customized;
        } else if (this.state.type === "js") {
            return this.state.resources.js[url].customized;
        }
        return false;
    }

    async loadResources() {
        const endLoad = log.perf("get_assets_editor_resources", () => ({
            key: this.viewKey,
            xmlFilter: this.state.xmlFilter,
            scssFilter: this.state.scssFilter,
        }));
        const resources = await this.keepLast.add(
            rpc("/website/get_assets_editor_resources", {
                key: this.viewKey,
                bundles: this.state.xmlFilter === "all",
                bundles_restriction: BUNDLES_RESTRICTION,
                only_user_custom_files: this.state.scssFilter === "custom",
            }),
        );
        endLoad(() => ({
            views: resources.views?.length,
            scssBundles: resources.scss?.length,
            jsBundles: resources.js?.length,
        }));
        this.state.resources = { xml: {}, js: {}, scss: {} };
        this.processResources(resources.views || [], "xml");
        this.processResources(resources.scss || [], "scss");
        this.processResources(resources.js || [], "js");
        const type = this.state.type;
        if (this.state.currentResource) {
            log.logic("loadResources keep current resource", () => ({
                type,
                id: this.state.currentResource.id,
            }));
            this.state.currentResource =
                this.state.resources[type][this.state.currentResource.id];
        }
        if (!this.state.currentResource) {
            log.logic("loadResources no current resource: default file", { type });
            this.setDefaultFile();
        }
        this.errors.length = 0;
    }

    processResources(resources, type) {
        log.pipeline("processResources", () => ({ type, count: resources.length }));
        if (type === "xml") {
            const indexedById = {};
            resources
                .filter((view) => view.active)
                .forEach((view) => {
                    view.type = "xml";
                    indexedById[view.id] = view;
                });
            Object.assign(this.state.resources.xml, indexedById);

            const roots = [];
            Object.values(this.state.resources.xml).forEach((view) => {
                view.level = 0;
                view.children = [];
            });
            Object.values(this.state.resources.xml).forEach((view) => {
                const parentId = view.inherit_id[0];
                const parent = parentId && this.state.resources.xml[parentId];
                if (parent) {
                    parent.children.push(view);
                } else {
                    roots.push(view);
                }
            });

            const sortedXML = [];
            const visit = (view, level) => {
                view.level = level;
                sortedXML.push(view);
                view.children.forEach((child) => {
                    visit(child, level + 1);
                });
            };
            roots.forEach((root) => {
                visit(root, 0);
            });
            this.state.sortedXML = sortedXML;

            Object.values(this.state.resources.xml).forEach((view) => {
                view.label = `${"-".repeat(view.level)} ${view.name}`;
                if (this.debug && view.xml_id) {
                    view.label += ` (${view.xml_id})`;
                }
            });
        } else if (type === "scss" || type === "js") {
            if (type === "scss") {
                this.state.sortedSCSS = resources;
            } else {
                this.state.sortedJS = resources;
            }

            resources.forEach(([bundle, files]) => {
                const indexedByUrl = {};
                files.forEach((file) => {
                    file.label = file.url.split("/").at(-1).split(".")[0];
                    if (this.debug) {
                        file.label += ` (${file.url})`;
                    }

                    file.bundle = bundle;
                    file.id = file.url;
                    file.type = type;
                    indexedByUrl[file.url] = file;
                });
                if (type === "scss") {
                    Object.assign(this.state.resources.scss, indexedByUrl);
                } else {
                    Object.assign(this.state.resources.js, indexedByUrl);
                }
            });
        }
    }

    /**
     * @returns {Promise}
     */
    async resetResource() {
        if (this.state.type === "xml") {
            log.logic("resetResource refused: xml views");
            throw new Error(_t("Reseting views is not supported yet"));
        }
        const resource = this.state.currentResource;
        const endReset = log.perf("reset_asset", () => ({
            url: resource.url,
            bundle: resource.bundle,
        }));
        await this.orm.call(
            "website.assets",
            "reset_asset",
            [resource.url, resource.bundle],
            {
                context: this.context,
            },
        );
        endReset();
        await this.loadResources();
        log.pipeline("resetResource reload page");
        this.website.contentWindow.location.reload();
    }

    async saveResources() {
        const { js, scss, xml } = this.state.resources;
        const toSave = {
            js: Object.values(js).filter((r) => r.dirty),
            scss: Object.values(scss).filter((r) => r.dirty),
            xml: sortBy(
                Object.values(xml).filter((r) => r.dirty),
                "id",
            ).reverse(),
        };
        log.pipeline("saveResources dirty", () => ({
            js: toSave.js.length,
            scss: toSave.scss.length,
            xml: toSave.xml.length,
        }));

        const endValidate = log.perf("saveResources validate");
        for (const [type, resources] of Object.entries(toSave)) {
            for (let i = 0; i < resources.length; i++) {
                const arch = resources[i].arch;
                const { isValid, error } =
                    type === "xml" ? checkXML(arch) : checkSCSS(arch);
                if (!isValid) {
                    log.logic("saveResources invalid resource", () => ({
                        type,
                        id: resources[i].id,
                        line: error.line,
                    }));
                    this.errors.push({ error, resource: resources[i] });
                }
            }
        }
        endValidate();
        if (this.errors.length) {
            log.logic("saveResources aborted: validation errors", () => ({
                errors: this.errors.length,
            }));
            if (
                !this.errors
                    .map(({ resource }) => resource.id)
                    .includes(this.state.currentResource?.id)
            ) {
                log.logic("saveResources switch to first erroneous resource");
                this.state.currentResource = this.errors[0].resource;
                this.state.type = this.errors[0].resource.type;
            }
            return;
        }

        const endSave = log.perf("saveResources save loop");
        for (const [type, resources] of Object.entries(toSave)) {
            for (const resource of resources) {
                if (type === "xml") {
                    await this.saveXML(resource);
                } else {
                    await this.saveSCSSorJS(resource);
                }
            }
        }
        endSave();
        await this.loadResources();
        log.pipeline("saveResources reload page");
        this.website.contentWindow.location.reload();
    }

    /**
     * @private
     * @param {Object} resource
     * @return {Promise}
     */
    async saveSCSSorJS(resource) {
        const { url, arch } = resource;
        const isJSFile = String(url).endsWith(".js");
        const bundle = isJSFile
            ? this.state.resources.js[url].bundle
            : this.state.resources.scss[url].bundle;
        const fileType = isJSFile ? "js" : "scss";
        const params = [url, bundle, arch, fileType];
        const endSaveAsset = log.perf("save_asset", { url, bundle, fileType });
        await this.orm.call("website.assets", "save_asset", params, {
            context: this.context,
        });
        endSaveAsset();
        delete resource.dirty;
    }

    /**
     * @param {Object} resource
     * @returns {Promise}
     */
    async saveXML(resource) {
        const { id, arch } = resource;
        const endSaveXml = log.perf("save_xml", { id });
        await rpc("/website/save_xml", {
            view_id: id,
            arch: arch,
        });
        endSaveXml();
        delete resource.dirty;
    }

    setDefaultFile() {
        log.logic("setDefaultFile", () => ({
            type: this.state.type,
            viewKey: this.viewKey,
        }));
        if (this.state.type === "xml") {
            const views = Object.values(this.state.resources.xml);
            let view = views.find((view) =>
                [view.id, view.xml_id].includes(this.viewKey),
            );
            if (!view) {
                log.logic("setDefaultFile xml: fallback lookup by key", () => ({
                    views: views.length,
                }));
                view = views.find((view) => view.key === this.viewKey);
            }
            this.state.currentResource = view || this.state.sortedXML[0] || false;
        } else if (this.state.type === "scss") {
            this.state.currentResource =
                this.state.resources.scss[
                    "/website/static/src/scss/user_custom_rules.scss"
                ];
        } else {
            this.state.currentResource =
                this.state.sortedJS.map(([_, files]) => files).flat()[0] || false;
        }
    }

    showErrorLine() {
        if (!this.editorRef.el) {
            return;
        }
        const resourceId = this.state.currentResource.id;
        const error = this.errors.find(
            ({ resource }) => resource.id === resourceId,
        )?.error;
        if (error) {
            const { line, message } = error;
            const gutterCell =
                this.editorRef.el.querySelectorAll(".ace_gutter-cell")[line - 1];
            if (gutterCell && !gutterCell.classList.contains("o_error")) {
                gutterCell.classList.add("o_error");
                gutterCell.setAttribute("data-tooltip", message);
                gutterCell.setAttribute("data-tooltip-position", "left");
            }
        }
    }

    clearErrorLine() {
        if (!this.editorRef.el) {
            return;
        }
        const allGutterCells = this.editorRef.el.querySelectorAll(".ace_gutter-cell");
        for (const gutterCell of allGutterCells) {
            gutterCell.classList.remove("o_error");
            gutterCell.removeAttribute("data-tooltip");
            gutterCell.removeAttribute("data-tooltip-position");
        }
    }

    onEditorChange(value) {
        const currentResource = this.state.currentResource;
        currentResource.arch = value;
        currentResource.dirty = true;
        this.errors.length = 0;
    }

    /**
     * @param {"xml"|"scss"|"js"} type
     */
    onFileTypeChange(type) {
        if (type !== this.state.type) {
            log.logic("onFileTypeChange", { type });
            this.state.type = type;
            this.setDefaultFile();
        }
    }

    /**
     * @param {"xml"|"scss"} type
     * @param {string} filter
     */
    onFilterChange(type, filter) {
        log.logic("onFilterChange reload resources", { type, filter });
        if (type === "scss") {
            this.state.scssFilter = filter;
        } else if (type === "xml") {
            this.state.xmlFilter = filter;
        }
        this.loadResources();
    }

    onFormat() {
        if (this.state.type === "xml") {
            const { isValid, error } = checkXML(this.state.currentResource.arch);
            log.logic("onFormat xml", () => ({ isValid, line: error?.line }));
            if (isValid) {
                this.state.currentResource.arch = formatXML(
                    this.state.currentResource.arch,
                );
            } else {
                this.errors.push({ error, resource: this.state.currentResource });
            }
        }
    }

    onReset() {
        log.lifecycle("onReset confirmation dialog");
        this.dialog.add(ConfirmationDialog, {
            title: _t("Careful"),
            body: _t(
                "If you reset this file, all your customizations will be lost as it will be reverted to the default file.",
            ),
            confirm: () => this.resetResource(),
            cancel: () => {},
        });
    }

    async onSave() {
        this.state.saving = true;
        const endOnSave = log.perf("onSave");
        try {
            await this.saveResources();
            endOnSave();
        } finally {
            this.state.saving = false;
        }
    }
}
