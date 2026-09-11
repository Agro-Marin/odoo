/** @odoo-module native */
import { EventBus, reactive } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { jsToPyLocale } from "@web/core/l10n/utils";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { isVisible } from "@web/core/utils/dom/ui";

import { FullscreenIndication } from "../components/fullscreen_indication/fullscreen_indication.js";
import { WebsiteLoader } from "../components/website_loader/website_loader.js";

const websiteSystrayRegistry = registry.category("website_systray");

export const unslugHtmlDataObject = (repr) => {
    const match = repr && repr.match(/(.+)\((-?\d+),(.*)\)/);
    if (!match) {
        return null;
    }
    return {
        model: match[1],
        id: match[2] | 0,
    };
};

const ANONYMOUS_PROCESS_ID = "ANONYMOUS_PROCESS_ID";

const log = makeLogger("website.service");

export const websiteService = {
    dependencies: ["orm", "action", "hotkey"],
    start(env, { orm, action, hotkey }) {
        let websites = [];
        let currentWebsiteId;
        const currentWebsiteIdList = [];
        let currentMetadata = {};
        let fullscreen;
        let pageDocument;
        let contentWindow;
        let lastUrl;
        let websitePublicEnv;
        let isRestrictedEditor;
        let isDesigner;
        let hasMultiWebsites;
        let actionJsId;
        const blockingProcesses = [];
        let modelNamesProm = null;
        const modelNames = {};
        let invalidateSnippetCache = false;
        let lastWebsiteId = null;

        const context = reactive({
            showResourceEditor: false,
            edition: false,
            isPublicRootReady: false,
            snippetsLoaded: false,
            isMobile: false,
        });
        const bus = new EventBus();

        hotkey.add(
            "escape",
            () => {
                if (
                    (!currentWebsiteId && !fullscreen) ||
                    (pageDocument && isVisible(pageDocument.querySelector(".modal")))
                ) {
                    return;
                }
                fullscreen = !fullscreen;
                document.body.classList.toggle("o_website_fullscreen", fullscreen);
                bus.trigger(
                    fullscreen
                        ? "FULLSCREEN-INDICATION-SHOW"
                        : "FULLSCREEN-INDICATION-HIDE",
                );
            },
            { global: true },
        );
        registry.category("main_components").add("FullscreenIndication", {
            Component: FullscreenIndication,
            props: { bus },
        });
        registry.category("main_components").add("WebsiteLoader", {
            Component: WebsiteLoader,
            props: { bus },
        });

        function addWebsiteId(id) {
            if (!currentWebsiteIdList.length) {
                currentWebsiteId = id;
            }
            currentWebsiteIdList.push(id);
        }

        function removeWebsiteId() {
            currentWebsiteIdList.shift();
            if (currentWebsiteIdList.length) {
                currentWebsiteId = currentWebsiteIdList[0];
            } else {
                currentWebsiteId = null;
            }
        }

        return {
            set currentWebsiteId(id) {
                log.lifecycle("currentWebsiteId", () => ({
                    from: currentWebsiteId,
                    to: id,
                }));
                if (id === null) {
                    removeWebsiteId();
                    return;
                }
                if (id && id !== lastWebsiteId) {
                    invalidateSnippetCache = true;
                    lastWebsiteId = id;
                }
                addWebsiteId(id);
                websiteSystrayRegistry.trigger("EDIT-WEBSITE");
            },
            get currentWebsite() {
                const currentWebsite = websites.find((w) => w.id === currentWebsiteId);
                if (currentWebsite) {
                    currentWebsite.metadata = currentMetadata;
                }
                return currentWebsite;
            },
            get currentWebsiteId() {
                return currentWebsiteId;
            },
            get websites() {
                return websites;
            },
            get context() {
                return context;
            },
            get bus() {
                return bus;
            },
            set pageDocument(document) {
                log.lifecycle("pageDocument", () => ({
                    url: document?.location?.href,
                }));
                pageDocument = document;
                if (!document) {
                    currentMetadata = {};
                    contentWindow = null;
                    return;
                }
                const { dataset } = document.documentElement;
                const isWebsitePage = dataset && dataset.websiteId;
                if (!isWebsitePage) {
                    currentMetadata = {};
                } else {
                    const {
                        mainObject,
                        seoObject,
                        isPublished,
                        canOptimizeSeo,
                        canPublish,
                        editableInBackend,
                        translatable,
                        viewXmlid,
                        defaultLangName,
                        langName,
                    } = dataset;
                    const contentMenus = [
                        ...new Map(
                            [
                                ...document.querySelectorAll("[data-content_menu_id]"),
                            ].map((menuEl) => [
                                menuEl.dataset.content_menu_id,
                                [
                                    menuEl.dataset.menu_name,
                                    menuEl.dataset.content_menu_id,
                                ],
                            ]),
                        ).values(),
                    ];
                    currentMetadata = {
                        path: document.location.href,
                        mainObject: unslugHtmlDataObject(mainObject),
                        seoObject: unslugHtmlDataObject(seoObject),
                        isPublished: isPublished === "True",
                        canOptimizeSeo: canOptimizeSeo === "True",
                        canPublish: canPublish === "True",
                        editableInBackend: editableInBackend === "True",
                        title: document.title,
                        translatable: !!translatable,
                        contentMenus,
                        editable: !!document.getElementById("wrapwrap"),
                        viewXmlid: viewXmlid,
                        lang: jsToPyLocale(
                            document.documentElement.getAttribute("lang"),
                        ),
                        defaultLangName: defaultLangName,
                        langName: langName,
                        direction: document.documentElement.querySelector(
                            "#wrapwrap.o_rtl",
                        )
                            ? "rtl"
                            : "ltr",
                    };
                }
                contentWindow = document.defaultView;
                websiteSystrayRegistry.trigger("CONTENT-UPDATED");
            },
            get pageDocument() {
                return pageDocument;
            },
            get contentWindow() {
                return contentWindow;
            },
            get websitePublicEnv() {
                return websitePublicEnv;
            },
            set websitePublicEnv(env) {
                websitePublicEnv = env;
                context.isPublicRootReady = !!env;
            },
            set lastUrl(url) {
                lastUrl = url;
            },
            get lastUrl() {
                return lastUrl;
            },
            get isRestrictedEditor() {
                return isRestrictedEditor === true;
            },
            get isDesigner() {
                return isDesigner === true;
            },
            get is404() {
                return currentMetadata.viewXmlid === "website.page_404";
            },
            get currentLocation() {
                const path = decodeURIComponent(this.contentWindow.location.pathname);
                if (!this.currentWebsite.metadata.translatable) {
                    return path;
                }
                const lang = path.split("/")[1];
                return path.slice(lang.length + 1);
            },
            get hasMultiWebsites() {
                return hasMultiWebsites === true;
            },
            get actionJsId() {
                return actionJsId;
            },
            set actionJsId(jsId) {
                actionJsId = jsId;
            },
            get invalidateSnippetCache() {
                return invalidateSnippetCache;
            },
            set invalidateSnippetCache(value) {
                invalidateSnippetCache = value;
            },

            goToWebsite({ websiteId, path, edition, translation, lang } = {}) {
                log.logic("goToWebsite", () => ({
                    websiteId,
                    path,
                    edition,
                    translation,
                    lang,
                }));
                this.websitePublicEnv = undefined;
                if (lang) {
                    invalidateSnippetCache = true;
                    path = `/website/lang/${encodeURIComponent(lang)}?r=${encodeURIComponent(
                        path,
                    )}`;
                }
                action.doAction("website.website_preview", {
                    clearBreadcrumbs: true,
                    props: {
                        websiteId: websiteId || currentWebsiteId || false,
                        path:
                            path ||
                            (contentWindow && contentWindow.location.href) ||
                            "/",
                        enableEditor: edition,
                        editTranslations: translation,
                    },
                });
            },
            async fetchUserGroups() {
                [isRestrictedEditor, isDesigner, hasMultiWebsites] = await Promise.all([
                    user.hasGroup("website.group_website_restricted_editor"),
                    user.hasGroup("website.group_website_designer"),
                    user.hasGroup("website.group_multi_website"),
                ]);
            },
            async fetchWebsites() {
                const endFetch = log.perf("fetchWebsites");
                websites = (
                    await orm.webSearchRead("website", [], {
                        specification: {
                            domain: {},
                            id: {},
                            name: {},
                            language_ids: {},
                            default_lang_id: { fields: { code: {} } },
                            cookies_bar: {},
                        },
                    })
                ).records;
                endFetch({ websites: websites.length });
            },
            blockPreview(showLoader, processId) {
                log.logic("blockPreview", () => ({
                    showLoader,
                    processId,
                    blocking: blockingProcesses.length,
                }));
                if (!blockingProcesses.length) {
                    bus.trigger("BLOCK", { showLoader });
                }
                blockingProcesses.push(processId || ANONYMOUS_PROCESS_ID);
            },
            unblockPreview(processId) {
                log.logic("unblockPreview", () => ({
                    processId,
                    blocking: blockingProcesses.length,
                }));
                const processIndex = blockingProcesses.indexOf(
                    processId || ANONYMOUS_PROCESS_ID,
                );
                if (processIndex > -1) {
                    blockingProcesses.splice(processIndex, 1);
                    if (blockingProcesses.length === 0) {
                        bus.trigger("UNBLOCK");
                    }
                }
            },
            showLoader(props) {
                bus.trigger("SHOW-WEBSITE-LOADER", props);
            },
            hideLoader() {
                bus.trigger("HIDE-WEBSITE-LOADER");
            },
            prepareOutLoader() {
                bus.trigger("PREPARE-OUT-WEBSITE-LOADER");
            },
            /**
             * @param {string} [model]
             * @returns {string}
             */
            async getUserModelName(
                model = this.currentWebsite.metadata.mainObject.model,
            ) {
                if (!modelNamesProm) {
                    modelNamesProm = orm
                        .call("ir.model", "get_available_models")
                        .then((modelsData) => {
                            for (const modelData of modelsData) {
                                modelNames[modelData["model"]] =
                                    modelData["display_name"];
                            }
                        })
                        .catch(() => {
                            modelNamesProm = null;
                        });
                }
                await modelNamesProm;
                return modelNames[model] || _t("Data");
            },
        };
    },
};

registry.category("services").add("website", websiteService);
