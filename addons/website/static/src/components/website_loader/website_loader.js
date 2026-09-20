/** @odoo-module native */
import { Component, EventBus, markup, useEffect, useState } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { rpc } from "@web/core/network";
import { _t } from "@web/core/translation";
import { sprintf } from "@web/core/utils/format/strings";
import { useBus, useService } from "@web/core/utils/hooks";

const log = makeLogger("website.component.website_loader");

export class WebsiteLoader extends Component {
    static props = {
        bus: EventBus,
    };
    static template = "website.website_loader";

    setup() {
        useLifecycleLog(log);
        this.website = useService("website");

        const initialState = {
            isVisible: false,
            title: "",
            flag: false,
            showTips: false,
            selectedFeatures: [],
            showWaitingMessages: false,
            progressPercentage: 0,
            bottomMessageTemplate: undefined,
            showLoader: true,
            showCloseButton: false,
        };

        const defaultMessages = [
            {
                title: _t("Building your website."),
                description: _t("Applying your colors and design..."),
                flag: "colors",
            },
            {
                title: _t("Building your website."),
                description: _t("Searching your images...."),
                flag: "images",
            },
            {
                title: _t("Building your website."),
                description: _t("Generating inspiring text..."),
                flag: "text",
            },
        ];

        let messagesInterval;

        this.state = useState({
            ...initialState,
        });
        this.waitingMessages = useState(defaultMessages);
        this.currentWaitingMessage = useState({ ...defaultMessages[0] });
        this.featuresInstallInfo = { nbInstalled: 0, total: undefined };

        useEffect(
            (selectedFeatures) => {
                if (this.state.showWaitingMessages) {
                    const messagesToDisplay = [...defaultMessages];
                    if (selectedFeatures.length > 0) {
                        messagesToDisplay.push(
                            ...this.getWaitingMessages(selectedFeatures),
                        );
                    }

                    log.pipeline("waiting messages prepared", () => ({
                        features: selectedFeatures.length,
                        messages: messagesToDisplay.length,
                    }));
                    this.waitingMessages.splice(
                        0,
                        this.waitingMessages.length,
                        ...messagesToDisplay,
                    );

                    this.trackModules(selectedFeatures).catch(console.error);

                    return () => {
                        log.lifecycle("trackModules timers cleared");
                        clearTimeout(this.trackModulesTimeout);
                        clearInterval(this.updateProgressInterval);
                    };
                }
            },
            () => [this.state.selectedFeatures],
        );

        useEffect(
            () => {
                if (this.state.showWaitingMessages) {
                    let msgIndex = 0;
                    messagesInterval = setInterval(() => {
                        msgIndex++;
                        const nextMessage = this.waitingMessages[msgIndex];
                        Object.assign(this.currentWaitingMessage, nextMessage);
                        if (this.waitingMessages.length - 1 === msgIndex) {
                            log.lifecycle("messages interval finished", { msgIndex });
                            clearInterval(messagesInterval);
                        }
                    }, 6000);
                    log.lifecycle("messages interval started");

                    return () => clearInterval(messagesInterval);
                }
            },
            () => [this.waitingMessages.length],
        );

        useEffect(
            (isVisible) => {
                if (isVisible) {
                    log.lifecycle("visible: beforeunload guard attached");
                    window.addEventListener(
                        "beforeunload",
                        this.showRefreshConfirmation,
                    );
                    if (
                        !this.state.selectedFeatures ||
                        this.state.selectedFeatures.length === 0
                    ) {
                        log.logic("no feature to install: plain progress bar");
                        this.initProgressBar();
                    }
                } else {
                    log.lifecycle("hidden: beforeunload guard removed");
                    window.removeEventListener(
                        "beforeunload",
                        this.showRefreshConfirmation,
                    );
                }

                return () => {
                    window.removeEventListener(
                        "beforeunload",
                        this.showRefreshConfirmation,
                    );
                    clearInterval(this.updateProgressInterval);
                };
            },
            () => [this.state.isVisible],
        );

        useBus(this.props.bus, "SHOW-WEBSITE-LOADER", (ev) => {
            const props = ev.detail;
            log.lifecycle("SHOW-WEBSITE-LOADER", () => ({
                title: props?.title,
                features: props?.selectedFeatures?.length,
                showWaitingMessages: props?.showWaitingMessages,
                flag: props?.flag,
            }));
            this.state.isVisible = true;
            for (const prop of [
                "title",
                "selectedFeatures",
                "showWaitingMessages",
                "bottomMessageTemplate",
                "showCloseButton",
                "flag",
            ]) {
                this.state[prop] = props && props[prop];
            }
            this.state.showLoader = props && props.showLoader !== false;
        });
        useBus(this.props.bus, "HIDE-WEBSITE-LOADER", () => {
            if (!this.state.isVisible) {
                log.logic("HIDE-WEBSITE-LOADER ignored: not visible");
                return;
            }
            log.lifecycle("HIDE-WEBSITE-LOADER");
            for (const key of Object.keys(initialState)) {
                this.state[key] = initialState[key];
            }
            clearInterval(messagesInterval);
            clearTimeout(this.trackModulesTimeout);
            clearInterval(this.updateProgressInterval);
        });
        useBus(this.props.bus, "PREPARE-OUT-WEBSITE-LOADER", () => {
            log.lifecycle("PREPARE-OUT-WEBSITE-LOADER");
            window.removeEventListener("beforeunload", this.showRefreshConfirmation);
        });
    }

    initProgressBar() {
        const nbModulesToInstall = this.featuresInstallInfo.total || 0;
        const isSomethingToInstall = nbModulesToInstall > 0;
        let currentProgress = 0;
        const progressStep = isSomethingToInstall ? 0.04 : 0.02;
        const progressForAfterModules = isSomethingToInstall ? 30 : 100;
        const progressForAllModules = 100 - progressForAfterModules;
        let lastTotalInstalled = 0;
        const progressPerModule = isSomethingToInstall
            ? progressForAllModules / nbModulesToInstall
            : 0;

        log.lifecycle("initProgressBar interval (re)started", () => ({
            nbModulesToInstall,
            installed: this.featuresInstallInfo.nbInstalled,
        }));
        clearInterval(this.updateProgressInterval);
        this.updateProgressInterval = setInterval(() => {
            if (this.featuresInstallInfo.nbInstalled !== lastTotalInstalled) {
                currentProgress = 0;
                lastTotalInstalled = this.featuresInstallInfo.nbInstalled;
            }
            currentProgress += progressStep;
            const limit =
                this.featuresInstallInfo.nbInstalled === nbModulesToInstall
                    ? progressForAfterModules
                    : progressPerModule;
            this.state.progressPercentage =
                lastTotalInstalled * progressPerModule +
                (Math.atan(currentProgress) / (Math.PI / 2)) * limit;
        }, 100);
    }
    /**
     * @param {integer[]} selectedFeatures
     */
    async trackModules(selectedFeatures) {
        const endTrack = log.perf("track_installing_modules", () => ({
            features: selectedFeatures.length,
        }));
        const installInfo = await rpc(
            "/website/track_installing_modules",
            {
                selected_features: selectedFeatures,
                total_features: this.featuresInstallInfo.total,
            },
            { silent: true },
        );
        endTrack(() => ({
            nbInstalled: installInfo.nbInstalled,
            total: installInfo.total,
        }));
        if (
            !this.featuresInstallInfo.total ||
            this.featuresInstallInfo.nbInstalled !== installInfo.nbInstalled
        ) {
            this.featuresInstallInfo = installInfo;
        }
        this.initProgressBar();
        if (this.featuresInstallInfo.nbInstalled !== this.featuresInstallInfo.total) {
            log.logic("trackModules not done: poll again in 1s", () => ({
                nbInstalled: this.featuresInstallInfo.nbInstalled,
                total: this.featuresInstallInfo.total,
            }));
            this.trackModulesTimeout = setTimeout(
                () => this.trackModules(selectedFeatures),
                1000,
            );
        }
    }

    /**
     * @param {integer[]} selectedFeatures
     * @returns {Object[]}
     */
    getWaitingMessages(selectedFeatures) {
        const websiteFeaturesMessages = [
            {
                id: 5,
                title: _t("Adding features."),
                name: _t("blog"),
                description: _t("Enabling your %s."),
                flag: "generic",
            },
            {
                id: 7,
                title: _t("Adding features."),
                name: _t("recruitment platform"),
                description: _t("Integrating your %s."),
                flag: "generic",
            },
            {
                id: 8,
                title: _t("Adding features."),
                name: _t("online store"),
                description: _t("Activating your %s."),
                flag: "generic",
            },
            {
                id: 9,
                title: _t("Adding features."),
                name: _t("online appointment system"),
                description: _t("Configuring your %s."),
                flag: "generic",
            },
            {
                id: 10,
                title: _t("Adding features."),
                name: _t("forum"),
                description: _t("Setting up your %s."),
                flag: "generic",
            },
            {
                id: 12,
                title: _t("Adding features."),
                name: _t("e-learning platform"),
                description: _t("Installing your %s."),
                flag: "generic",
            },
            {
                id: "last",
                title: _t("Finalizing."),
                description: _t("Activating the last features."),
                flag: "generic",
            },
        ];

        const filteredIds = [...selectedFeatures, "last"];
        const messagesList = websiteFeaturesMessages.filter((msg) => {
            if (filteredIds.includes(msg.id)) {
                if (msg.name) {
                    const highlight = markup`<span class="o_website_loader_text_highlight">${msg.name}</span>`;
                    msg.description = markup(sprintf(msg.description, highlight));
                }
                return true;
            }
        });
        log.pipeline("getWaitingMessages", () => ({
            selected: selectedFeatures.length,
            messages: messagesList.length,
        }));
        return messagesList;
    }

    /**
     * @param {Event} ev
     */
    showRefreshConfirmation = (ev) => {
        if (this.state.isVisible) {
            log.logic("beforeunload blocked: loader visible");
            ev.preventDefault();
            ev.returnValue = "";
            return ev.returnValue;
        }
    };

    close() {
        log.logic("close button");
        this.website.hideLoader();
    }
}
