/** @odoo-module native */
import { LocalOverlayContainer } from "@html_editor/local_overlay_container";
import {
    Component,
    onMounted,
    onWillDestroy,
    onWillStart,
    onWillUnmount,
    status,
    useComponent,
    useEffect,
    useRef,
    useState,
    useSubEnv,
} from "@odoo/owl";
import { ResizablePanel } from "@web/components/resizable_panel";
import { LazyComponent, loadBundle } from "@web/core/assets";
import { browser } from "@web/core/browser/browser";
import {
    isBrowserChrome,
    isBrowserMicrosoftEdge,
} from "@web/core/browser/feature_detection";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { router } from "@web/core/browser/router";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { RPCError } from "@web/core/network";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { Deferred } from "@web/core/utils/concurrency";
import { getScrollingElement } from "@web/core/utils/dom/scrolling";
import { uniqueId } from "@web/core/utils/functions";
import { useBus, useChildRef, useService } from "@web/core/utils/hooks";
import { effect } from "@web/core/utils/reactive";
import { renderToElement } from "@web/core/utils/render";
import { redirect } from "@web/core/utils/urls";
import { session } from "@web/session";
import { standardActionServiceProps } from "@web/webclient/actions";
import { AddPageDialog } from "@website/components/dialog/add_page_dialog";
import { ResourceEditor } from "@website/components/resource_editor/resource_editor";

import { CreatePageMessage } from "./create_page_message.js";
import { isHTTPSorNakedDomainRedirection } from "./utils.js";
import { WebsiteSystrayItem } from "./website_systray_item.js";

const websiteSystrayRegistry = registry.category("website_systray");

const log = makeLogger("website.builder");

export class WebsiteBuilderClientAction extends Component {
    static template = "website.WebsiteBuilderClientAction";
    static components = {
        LazyComponent,
        LocalOverlayContainer,
        ResizablePanel,
        ResourceEditor,
        CreatePageMessage,
    };
    static props = {
        ...standardActionServiceProps,
        editTranslations: { type: Boolean, optional: true },
        enableEditor: { type: Boolean, optional: true },
        path: { type: String, optional: true },
        websiteId: { type: [Number, { value: false }], optional: true },
    };

    static extractProps(action) {
        return {
            editTranslations: action.params?.edit_translations || false,
            enableEditor: action.params?.enable_editor || false,
            path: action.params?.path,
            websiteId: action.params?.website_id || false,
        };
    }

    setup() {
        useLifecycleLog(log);
        this.target = null;
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.websiteService = useService("website");
        this.ui = useService("ui");
        this.title = useService("title");
        this.hotkeyService = useService("hotkey");
        this.websiteService.websitePublicEnv = undefined;
        this.iframeFallbackUrl = "/website/iframefallback";
        this.iframefallback = useRef("iframefallback");

        this.websiteContent = useRef("iframe");
        this.cleanups = [];

        this.snippetsTemplate = "website.snippets";
        this.isNavigatingToAnotherPage = null;

        useSubEnv({
            builderRef: useRef("container"),
        });
        this.state = useState({
            isEditing: false,
            showSidebar: true,
            key: 1,
            is404: false,
        });
        this.websiteContext = useState(this.websiteService.context);
        this.component = useComponent();

        useBus(
            websiteSystrayRegistry,
            "CONTENT-UPDATED",
            () => (this.state.is404 = this.websiteService.is404),
        );

        onMounted(() => {
            effect(
                (websiteContext) => {
                    if (status(this.component) === "destroyed") {
                        return;
                    }
                    this.toggleIsMobile(websiteContext.isMobile);
                },
                [this.websiteContext],
            );
        });

        this.overlayRef = useChildRef();
        useSubEnv({
            localOverlayContainerKey: uniqueId("website"),
        });
        this.websitePreviewRef = useRef("website_preview");

        onWillStart(async () => {
            const updateWebsiteId = (websiteId) => {
                const encodedPath = encodeURIComponent(this.path);
                this.initialUrl = `/website/force/${encodeURIComponent(
                    websiteId,
                )}?path=${encodedPath}`;
                this.websiteService.currentWebsiteId = websiteId;
            };
            const proms = [
                this.websiteService.fetchWebsites(),
                this.websiteService.fetchUserGroups(),
            ];
            if (this.websiteId) {
                updateWebsiteId(this.websiteId);
                await Promise.all(proms);
            } else {
                const [backendWebsiteRepr] = await Promise.all([
                    this.orm.call("website", "get_current_website"),
                    ...proms,
                ]);
                updateWebsiteId(backendWebsiteRepr[0]);
            }
        });
        onMounted(() => {
            this.addListeners(document);
            this.addSystrayItems();
            const edition = !!(this.enableEditor || this.editTranslations);
            if (edition) {
                this.onEditPage();
            }
            if (!this.ui.isSmall) {
                loadBundle("website.website_builder_assets")
                    .then(() =>
                        this.env.services["html_builder.snippets"]
                            ?.getSnippetModel(this.snippetsTemplate)
                            .reload({
                                lang: this.websiteService.currentWebsite
                                    ?.default_lang_id.code,
                                website_id: this.websiteService.currentWebsite?.id,
                            }),
                    )
                    .catch((error) =>
                        console.warn("[website] snippet preload skipped:", error),
                    );
            }
        });
        onWillUnmount(() => {
            for (const fn of this.cleanups) {
                fn();
            }
        });
        this.publicRootReady = new Deferred();
        this.setIframeLoaded();
        this.addSystrayItems();
        onWillDestroy(() => {
            websiteSystrayRegistry.remove("website.WebsiteSystrayItem");
            this.websiteService.currentWebsiteId = null;
            websiteSystrayRegistry.trigger("EDIT-WEBSITE");
        });

        effect(
            (state) => {
                this.websiteContext.edition = state.isEditing;
                if (!state.isEditing) {
                    this.addSystrayItems();
                }
            },
            [this.state],
        );
        useEffect(
            (isEditing) => {
                document
                    .querySelector("body")
                    .classList.toggle("o_builder_open", isEditing);
                if (isEditing) {
                    websiteSystrayRegistry.remove("website.WebsiteSystrayItem");
                    websiteSystrayRegistry.trigger("EDIT-WEBSITE");
                    this.navBarTimeout = setTimeout(() => {
                        document
                            .querySelector(".o_builder_open .o_main_navbar")
                            ?.classList.add("d-none");
                    }, 200);
                } else {
                    document
                        .querySelector(".o_main_navbar")
                        ?.classList.remove("d-none");
                }
                return () => clearTimeout(this.navBarTimeout);
            },
            () => [this.state.isEditing],
        );
    }

    get testMode() {
        return !!session.test_mode;
    }

    get websiteBuilderProps() {
        const iframeLoaded = this.iframeLoaded.then((el) =>
            this.waitForIframeReady().then(() => el),
        );
        const builderProps = {
            closeEditor: this.reloadIframeAndCloseEditor.bind(this),
            editableSelector: "#wrapwrap",
            reloadEditor: this.reloadEditor.bind(this),
            snippetsName: this.snippetsTemplate,
            toggleMobile: this.toggleMobile.bind(this),
            installSnippetModule: this.installSnippetModule.bind(this),
            overlayRef: this.overlayRef,
            iframeLoaded: iframeLoaded,
            isMobile: this.websiteContext.isMobile,
            config: {
                initialTarget: this.target,
                initialTab:
                    this.initialTab || (this.translation ? "customize" : "blocks"),
                builderSidebar: {
                    withHiddenSidebar: async (cb) => {
                        try {
                            this.state.showSidebar = false;
                            return await cb();
                        } finally {
                            this.state.showSidebar = true;
                        }
                    },
                    toggle: (show) => {
                        this.state.showSidebar = show ?? !this.state.showSidebar;
                    },
                },
                isTranslationMode: this.translation,
            },
        };
        return { translation: this.translation, builderProps };
    }

    get systrayProps() {
        return {
            onNewPage: this.onNewPage.bind(this),
            onEditPage: this.onEditPage.bind(this),
            iframeLoaded: this.iframeLoaded,
        };
    }

    addSystrayItems() {
        if (!websiteSystrayRegistry.contains("website.WebsiteSystrayItem")) {
            websiteSystrayRegistry.add(
                "website.WebsiteSystrayItem",
                {
                    Component: WebsiteSystrayItem,
                    props: this.systrayProps,
                    isDisplayed: () => true,
                },
                { sequence: -100 },
            );
            websiteSystrayRegistry.trigger("EDIT-WEBSITE");
        }
    }

    onNewPage(keepUrl = false) {
        const params = {
            websiteId: this.websiteService.currentWebsite.id,
        };
        if (keepUrl) {
            params.forcedURL = this.websiteService.currentLocation;
        }
        this.dialog.add(AddPageDialog, params);
    }

    async onEditPage() {
        log.logic("onEditPage", () => ({
            iframe: Boolean(this.websiteContent.el),
            editing: this.state.isEditing,
        }));
        if (!this.websiteContent.el) {
            await this.iframeLoaded;
        }
        this.websiteContext.showResourceEditor = false;
        this.blockIframe();

        if (this.isNavigatingToAnotherPage) {
            await this.isNavigatingToAnotherPage;
        }

        await this.loadIframeAndBundles(true);
        window.document.dispatchEvent(
            new CustomEvent("edit_page", {
                detail: {
                    iframeDocument: this.websiteContent.el.contentDocument,
                },
            }),
        );
        this.unblockIframe();
        this.state.isEditing = true;
    }
    /**
     * @param {Boolean} isEditing
     */
    async loadIframeAndBundles(isEditing) {
        const endLoad = log.perf("loadIframeAndBundles");
        await this.iframeLoaded;
        if (isEditing) {
            await this.publicRootReady;
            await this.loadAssetsEditBundle();
        }
        endLoad({ isEditing });
    }

    async loadAssetsEditBundle() {
        await this.waitForIframeReady();
        await Promise.all([
            loadBundle("website.assets_inside_builder_iframe", {
                targetDoc: this.websiteContent.el.contentDocument,
            }),
        ]);
    }

    replaceBrowserUrl() {
        const iframe = this.websiteContent.el;
        if (!iframe || !iframe.contentWindow) {
            return;
        }

        if (
            !isHTTPSorNakedDomainRedirection(
                iframe.contentWindow.location.origin,
                window.location.origin,
            )
        ) {
            history.replaceState(history.state, document.title, "/odoo");
            return;
        }
        const currentTitle = iframe.contentDocument.title;
        history.replaceState(
            history.state,
            currentTitle,
            iframe.contentDocument.location.href,
        );
        this.title.setParts({ action: currentTitle });
        const frontendIconEl =
            iframe.contentDocument.querySelector("link[rel~='icon']");
        if (frontendIconEl) {
            document.querySelector("link[rel~='icon']").href = frontendIconEl.href;
        }
    }

    onIframeLoad(ev) {
        log.lifecycle("onIframeLoad", () => ({
            url: this.websiteContent.el?.contentWindow?.location?.href,
        }));
        const iframe = this.websiteContent.el;
        iframe.contentDocument.body.setAttribute("is-ready", "false");
        if (isBrowserChrome() && !iframe.src.includes("iframe_reload")) {
            try {
                iframe.contentWindow.location.href;
            } catch (err) {
                if (err.name === "SecurityError") {
                    ev.stopImmediatePropagation();
                    const srcUrl = new URL(iframe.src);
                    const pathUrl = new URL(
                        srcUrl.searchParams.get("path"),
                        srcUrl.origin,
                    );
                    pathUrl.searchParams.set("iframe_reload", "1");
                    srcUrl.searchParams.set(
                        "path",
                        `${pathUrl.pathname}${pathUrl.search}`,
                    );
                    iframe.src = srcUrl.toString();
                    return;
                } else {
                    throw err;
                }
            }
        }
        if (this.lastPageURL !== iframe.contentWindow.location.href) {
            this.websiteService.context.showResourceEditor = false;
        }
        this.websiteService.pageDocument = this.websiteContent.el.contentDocument;
        const url = new URL(this.websiteService.contentWindow.location.href);
        if (url.searchParams.has("edit_translations")) {
            deleteQueryParam(
                "edit_translations",
                this.websiteService.contentWindow,
                true,
            );
        }

        this.toggleIsMobile(this.websiteContext.isMobile);
        this.preparePublicRootReady();
        this.setupClickListener();
        this.replaceBrowserUrl();
        this.resolveIframeLoaded();
        this.addWelcomeMessage();
        this.websiteService.hideLoader();
        this.lastPageURL = iframe.contentWindow.location.href;

        if (this.isNavigatingToAnotherPage) {
            this.isNavigatingToAnotherPage.resolve();
            this.isNavigatingToAnotherPage = null;
        }
    }

    blockIframe() {
        this.websiteContent.el.setAttribute("inert", "");
    }
    unblockIframe() {
        this.websiteContent.el.removeAttribute("inert");
    }

    setupClickListener() {
        this.websiteContent.el.contentDocument.addEventListener("click", (ev) => {
            if (!this.state.isEditing) {
                this.websiteContent.el.dispatchEvent(new MouseEvent("click", ev));
            } else {
                ev.preventDefault();
            }
            const linkEl = ev.target.closest("[href]");
            if (!linkEl) {
                return;
            }

            const { href, target } = linkEl;
            if (href && target !== "_blank" && !this.state.isEditing) {
                if (isTopWindowURL(linkEl)) {
                    ev.preventDefault();
                    try {
                        browser.location.assign(href);
                    } catch {
                        this.notification.add(_t("%s is not a valid URL.", href), {
                            title: _t("Invalid URL"),
                            type: "danger",
                        });
                    }
                } else if (
                    this.websiteContent.el.contentWindow.location.pathname !==
                    new URL(href).pathname
                ) {
                    this.websiteService.websitePublicEnv = undefined;

                    this.isNavigatingToAnotherPage = new Deferred();
                }
            }
        });
    }

    get editTranslations() {
        return this.props.editTranslations || !!router.current.edit_translations;
    }

    get enableEditor() {
        return this.props.enableEditor || !!router.current.enable_editor;
    }

    get path() {
        let path = this.props.path || router.current.path;
        if (path) {
            const url = new URL(path, window.location.origin);
            if (isTopWindowURL(url)) {
                path = "/";
            } else {
                path = url.pathname + url.search;
            }
        } else {
            path = "/";
        }
        return path;
    }

    get websiteId() {
        return this.props.websiteId || router.current.website_id || false;
    }

    waitForIframeReady() {
        return new Promise((resolve) => {
            const doc = this.websiteContent.el.contentDocument;
            if (doc.body.getAttribute("is-ready") === "true") {
                resolve();
            } else {
                const observer = new MutationObserver(() => {
                    if (doc.body.getAttribute("is-ready") === "true") {
                        observer.disconnect();
                        resolve();
                    }
                });
                observer.observe(doc.body, {
                    attributes: true,
                    attributeFilter: ["is-ready"],
                });
            }
        });
    }

    async reloadEditor(param = {}) {
        log.logic("reloadEditor", () => ({
            initialTab: param.initialTab,
            url: param.url,
            target: Boolean(param.target),
        }));
        this.initialTab = param.initialTab;
        this.target = param.target || null;
        await this.reloadIframe(this.state.isEditing, param.url);
        this.state.key++;
    }

    async reloadIframeAndCloseEditor() {
        this.initialTab = null;
        this.target = null;
        const isEditing = false;
        this.state.isEditing = isEditing;
        this.addSystrayItems();
        await this.reloadIframe(isEditing);
    }

    async reloadIframe(isEditing = true, url) {
        log.pipeline("reloadIframe", () => ({ isEditing, url }));
        this.ui.block();
        this.preparePublicRootReady();
        this.setIframeLoaded();
        this.websiteService.websitePublicEnv = undefined;
        if (url) {
            const urlObj = new URL(url, this.websiteContent.el.contentWindow.location);
            const pathSegments = urlObj.pathname.split("/").map(encodeURIComponent);
            const encodedPath = pathSegments.join("/");
            this.websiteContent.el.contentWindow.location.href = new URL(
                encodedPath,
                this.websiteContent.el.contentWindow.location,
            );
        } else {
            this.websiteContent.el.contentWindow.location.reload();
        }
        await this.loadIframeAndBundles(isEditing);
        this.ui.unblock();
    }

    reloadWebClient() {
        const currentPath = encodeURIComponent(window.location.pathname);
        const websiteId = this.websiteService.currentWebsite.id;
        redirect(
            `/odoo/action-website.website_preview?website_id=${encodeURIComponent(
                websiteId,
            )}&path=${currentPath}&enable_editor=1`,
        );
    }

    async installSnippetModule(snippet, beforeInstall) {
        this.dialog.closeAll();
        try {
            this.ui.block();
            await beforeInstall();
            await this.orm.call("ir.module.module", "button_immediate_install", [
                [parseInt(snippet.moduleId)],
            ]);
            this.reloadWebClient();
        } catch (e) {
            if (e instanceof RPCError) {
                const message = _t(
                    "Could not install module %s",
                    snippet.moduleDisplayName,
                );
                this.notification.add(message, {
                    type: "danger",
                    sticky: true,
                });
                return;
            }
            throw e;
        } finally {
            this.ui.unblock();
        }
    }

    preparePublicRootReady() {
        const deferred = new Deferred();
        this.publicRootReady = deferred;
        this.websiteContent.el.contentWindow.addEventListener(
            "PUBLIC-ROOT-READY",
            (event) => {
                this.websiteService.websitePublicEnv = event.detail.env;
                deferred.resolve();
            },
            { once: true },
        );
    }

    async addWelcomeMessage() {
        if (this.websiteService.isRestrictedEditor && !this.state.isEditing) {
            const wrapEl = this.websiteContent.el.contentDocument.querySelector(
                "#wrapwrap.homepage #wrap",
            );
            if (wrapEl && !wrapEl.innerHTML.trim()) {
                this.welcomeMessageEl = renderToElement(
                    "website.homepage_editor_welcome_message",
                );
                wrapEl.replaceChildren(this.welcomeMessageEl);
            }
        }
    }

    setIframeLoaded() {
        this.iframeLoaded = new Promise((resolve) => {
            this.resolveIframeLoaded = () => {
                this.unregisterHotkeyIframe?.();
                this.unregisterHotkeyIframe = this.hotkeyService.registerIframe(
                    this.websiteContent.el,
                );
                if (!this._hotkeyIframeCleanupRegistered) {
                    this._hotkeyIframeCleanupRegistered = true;
                    this.cleanups.push(() => this.unregisterHotkeyIframe?.());
                }
                this.websiteContent.el.contentWindow.addEventListener(
                    "beforeunload",
                    this.onPageUnload.bind(this),
                );

                this.addListeners(this.websiteContent.el.contentDocument);
                this.iframefallback.el?.contentDocument.documentElement.replaceChildren();
                resolve(this.websiteContent.el);
            };
        });
    }

    onPageUnload() {
        const websiteDoc = this.websiteContent.el?.contentDocument;
        const fallBackDoc = this.iframefallback.el?.contentDocument;
        if (!this.state.isEditing && websiteDoc && fallBackDoc) {
            fallBackDoc.documentElement.replaceWith(
                websiteDoc.documentElement.cloneNode(true),
            );
            const currentScrollEl = getScrollingElement(websiteDoc);
            const scrollElement = getScrollingElement(fallBackDoc);
            scrollElement.scrollTop = currentScrollEl.scrollTop;
            this.cleanIframeFallback();
        }
    }

    cleanIframeFallback() {
        const iframesEl = this.iframefallback.el.contentDocument.querySelectorAll(
            'iframe[src]:not([src=""])',
        );
        for (const iframeEl of iframesEl) {
            const url = new URL(iframeEl.src);
            url.searchParams.delete("autoplay");
            iframeEl.src = url.toString();
        }
    }

    toggleMobile() {
        this.websiteService.context.isMobile = !this.websiteService.context.isMobile;
    }

    toggleIsMobile(isMobile) {
        this.websitePreviewRef.el.classList.toggle("o_is_mobile", isMobile);
        this.websiteContent.el?.contentDocument.documentElement.classList.toggle(
            "o_is_mobile",
            isMobile,
        );
    }

    get aceEditorWidth() {
        const storedWidth = browser.localStorage.getItem("ace_editor_width");
        return storedWidth ? parseInt(storedWidth) : 720;
    }

    onResourceEditorResize(width) {
        browser.localStorage.setItem("ace_editor_width", width);
    }

    get translation() {
        return this.websiteService.currentWebsite.metadata.translatable;
    }

    /**
     * @param {KeyboardEvent} ev
     */
    onKeydownRefresh(ev) {
        const hotkey = getActiveHotkey(ev);
        if (hotkey !== "control+r" && hotkey !== "f5") {
            return;
        }
        if (this.websiteService.contentWindow === undefined) {
            return;
        }
        ev.preventDefault();
        const path = this.websiteService.contentWindow.location;
        const debugMode = this.env.debug ? `&debug=${this.env.debug}` : "";
        redirect(
            `/odoo/action-website.website_preview?path=${encodeURIComponent(path)}${debugMode}`,
        );
    }

    /**
     * @param {HTMLElement} target
     */
    addListeners(target) {
        const listener = (ev) => this.onKeydownRefresh(ev);
        target.addEventListener("keydown", listener);
        this.cleanups.push(() => {
            target.removeEventListener("keydown", listener);
        });
    }

    get isMicrosoftEdge() {
        return isBrowserMicrosoftEdge();
    }
}

function deleteQueryParam(param, target = window, adaptBrowserUrl = false) {
    const url = new URL(target.location.href);
    url.searchParams.delete(param);
    target.history.replaceState(target.history.state, null, url);
    if (adaptBrowserUrl) {
        deleteQueryParam(param);
    }
}

/**
 * @param {string} host
 * @param {string} pathname
 */
function isTopWindowURL({ host, pathname }) {
    for (const fn of registry.category("isTopWindowURL").getAll()) {
        if (fn({ host, pathname })) {
            return true;
        }
    }
    return false;
}

registry
    .category("isTopWindowURL")
    .add("html_builder.website_builder_action", ({ host, pathname }) => {
        const backendRoutes = ["/web", "/web/session/logout", "/odoo"];
        return (
            host !== window.location.host ||
            (pathname &&
                (backendRoutes.includes(pathname) ||
                    pathname.startsWith("/@/") ||
                    pathname.startsWith("/odoo/") ||
                    pathname.startsWith("/web/content/") ||
                    pathname.startsWith("/document/share/")))
        );
    });

registry.category("actions").add("website_preview", WebsiteBuilderClientAction);
