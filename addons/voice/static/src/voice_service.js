// @ts-check
/** @odoo-module native */

import { reactive, toRaw } from "@odoo/owl";
import { normalize } from "@web/core/l10n/utils";
import { luxon } from "@web/core/l10n/luxon";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";

import { firstAvailableEngine } from "./engines/voice_engines.js";
import { execute, targetView, voiceExecutorRegistry } from "./executor.js";
import { collectTargets } from "./numbers/targets.js";
import {
    guardNegation,
    interpret,
    isNegated,
    RISK,
} from "./interpreter/interpreter.js";
import { compileVocabulary } from "./interpreter/vocabulary.js";

const MAX_DONE = 5;

/**
 * What to ask when the grammar understood nothing:
 * `({ text, vocabulary }) => Promise<Proposal[]>`, in sequence order.
 */
export const voiceFallbackRegistry = registry.category("voice_fallbacks");
const MAX_NAME_SEARCH = 8;

/**
 * @typedef {import("./interpreter/interpreter.js").Proposal} Proposal
 * @typedef {import("./interpreter/interpreter.js").Interpretation} Interpretation
 * @typedef {{ description: string, undo: import("./executor.js").Undo, fromModel: boolean }} Done
 */

/** @returns {string} */
function speechLang() {
    return (user.lang || "en_US").replace("_", "-");
}

export class VoiceService {
    /**
     * @param {Record<string, any>} services
     * @param {Record<string, any>} allServices for what a registered executor needs
     */
    constructor(services, allServices) {
        this.services = services;
        this.allServices = allServices;
        this.state = reactive({
            open: false,
            listening: false,
            busy: false,
            heard: "",
            interim: "",
            message: "",
            help: false,
            notice: "",
            /** @type {Done[]} */
            done: [],
            /** @type {Proposal | null} */
            pending: null,
            /** @type {Proposal[]} */
            candidates: [],
            /** @type {Proposal | null} */
            blocked: null,
            /** @type {{ n: number, top: number, left: number }[]} */
            numbers: [],
            /** @type {{ label: string, stopping: boolean } | null} */
            session: null,
        });
        /** @type {(() => Promise<any>) | null} */
        this.stopCurrentSession = null;
        /** @type {import("./numbers/targets.js").Target[]} */
        this.targets = [];
        this.hideNumbers = this.hideNumbers.bind(this);
        /** @type {AbortController | null} */
        this.abort = null;
        /** @type {{ vocabulary: any, target: any, targets: import("./numbers/targets.js").Target[] }} */
        this.lastSaid = { vocabulary: null, target: null, targets: [] };
        /** @type {((value: boolean) => void) | null} */
        this.acknowledge = null;
    }

    /**
     * Each proposal keeps the view it was said to: a palette or a dialog
     * opened since takes the active element, not the user's intent.
     *
     * @param {string} text
     * @param {{ withTargets?: boolean }} [options] the palette is a dialog of
     *   its own, whose items are not what the user means by "click"
     * @returns {Interpretation}
     */
    interpret(text, { withTargets = true } = {}) {
        const target = this.services.active_view.current;
        const vocabulary = this.vocabulary(target);
        const targets = withTargets ? this.currentTargets() : [];
        vocabulary.targets = targets.map(({ label, risk }) => ({ label, risk }));
        vocabulary.numbersShown = withTargets && this.state.numbers.length > 0;
        vocabulary.canDictate = voiceExecutorRegistry.contains("dictate");
        this.lastSaid = { vocabulary, target, targets };
        return this.bind(interpret(text, vocabulary));
    }

    /**
     * @param {Interpretation} interpretation
     * @returns {Interpretation}
     */
    bind(interpretation) {
        const { target, targets } = this.lastSaid;
        const { proposals, candidates, blocked } = interpretation;
        for (const proposal of [
            ...proposals,
            ...candidates,
            ...(blocked ? [blocked] : []),
        ]) {
            proposal.target = target;
            if (proposal.kind === "click_target") {
                proposal.element = targets[proposal.index].el;
            }
        }
        return interpretation;
    }

    /**
     * @param {string} text
     * @returns {Promise<Interpretation | null>}
     */
    async fallback(text) {
        for (const ask of voiceFallbackRegistry.getAll()) {
            this.state.busy = true;
            try {
                const proposals = await ask({
                    text,
                    vocabulary: this.lastSaid.vocabulary,
                });
                if (proposals?.length) {
                    for (const proposal of proposals) {
                        proposal.fromModel = true;
                    }
                    return this.bind(
                        guardNegation(
                            { text, proposals, candidates: [], blocked: null },
                            isNegated(text),
                        ),
                    );
                }
            } catch {
                continue;
            } finally {
                this.state.busy = false;
            }
        }
        return null;
    }

    /** @param {import("@web/views/active_view").ActiveView | null} [target] */
    vocabulary(target = this.services.active_view.current) {
        const { menu, home_menu, command, ui } = this.services;
        const commands = command
            .getCommands(ui.activeElement)
            .filter((/** @type {any} */ c) => !c.isAvailable || c.isAvailable())
            .map((/** @type {any} */ c) => ({
                name: c.name,
                category: c.category,
                action: c.action,
            }));
        return compileVocabulary({
            menu,
            activeView: target,
            homeMenu: home_menu,
            commands,
            today: luxon.DateTime.now(),
        });
    }

    /**
     * The names worth biasing a recogniser towards, most specific first.
     *
     * @returns {string[]}
     */
    phrases() {
        const vocabulary = this.vocabulary();
        const view = vocabulary.view;
        return [
            ...(view?.form?.buttons.map((button) => button.label) || []),
            ...(view?.form?.fields.map((field) => field.label) || []),
            ...(view?.filters.map((filter) => filter.label) || []),
            ...(view?.groupBys.map((groupBy) => groupBy.label) || []),
            ...vocabulary.menus.filter((term) => term.isApp).map((term) => term.label),
        ];
    }

    clear() {
        Object.assign(this.state, {
            message: "",
            help: false,
            pending: null,
            candidates: [],
            blocked: null,
        });
    }

    close() {
        this.stop();
        this.hideNumbers();
        this.clear();
        Object.assign(this.state, { open: false, heard: "", interim: "", done: [] });
    }

    /** @param {string} text */
    async submit(text) {
        this.clear();
        Object.assign(this.state, { open: true, heard: text, interim: "" });
        let interpretation = this.interpret(text);
        const { proposals, candidates, blocked } = interpretation;
        if (!proposals.length && !candidates.length && !blocked) {
            interpretation = (await this.fallback(text)) || interpretation;
        }
        await this.handle(interpretation);
    }

    /**
     * @param {string} text
     * @param {Proposal} proposal one the user already chose, from the palette
     */
    async accept(text, proposal) {
        this.clear();
        Object.assign(this.state, { open: true, heard: text, interim: "" });
        await this.propose(proposal);
    }

    /** @param {Interpretation} interpretation */
    async handle(interpretation) {
        if (interpretation.blocked) {
            this.state.blocked = interpretation.blocked;
            this.state.message = _t(
                "That sounded like a “no”: %s was not done.",
                interpretation.blocked.description,
            );
            return;
        }
        if (interpretation.candidates.length) {
            this.state.candidates = interpretation.candidates;
            return;
        }
        if (!interpretation.proposals.length) {
            this.state.message = _t("I did not understand “%s”.", interpretation.text);
            this.state.help = true;
            return;
        }
        for (const proposal of interpretation.proposals) {
            await this.propose(proposal);
        }
    }

    /** @param {Proposal} proposal */
    async propose(proposal) {
        const resolved = await this.resolve(proposal);
        if (resolved.length !== 1) {
            this.state.candidates = resolved;
            if (!resolved.length) {
                this.state.message = _t("Nothing matches “%s”.", proposal.query);
            }
            return;
        }
        if (resolved[0].risk === RISK.COMMIT) {
            this.state.pending = resolved[0];
            return;
        }
        await this.run(resolved[0]);
    }

    /**
     * A relation named by a word becomes the record of that name, or a
     * choice when several records answer to it.
     *
     * @param {Proposal} proposal
     * @returns {Promise<Proposal[]>}
     */
    async resolve(proposal) {
        if (proposal.kind !== "set_field" || proposal.query === undefined) {
            return [proposal];
        }
        const found = await this.services.orm.call(
            proposal.relation,
            "name_search",
            [],
            {
                name: proposal.query,
                limit: MAX_NAME_SEARCH,
            },
        );
        const records = found.map(
            (/** @type {[number, string]} */ [id, displayName]) => ({
                id,
                display_name: displayName,
            }),
        );
        const exact = records.filter(
            (/** @type {any} */ r) =>
                normalize(r.display_name) === normalize(proposal.query),
        );
        const chosen = exact.length === 1 ? exact : records;
        return chosen.map((/** @type {any} */ record) => {
            const { query, ...rest } = proposal;
            return {
                ...rest,
                value: record,
                description: proposal.description.replace(query, record.display_name),
            };
        });
    }

    /** @returns {import("./numbers/targets.js").Target[]} */
    currentTargets() {
        return this.state.numbers.length
            ? this.targets
            : collectTargets(this.services.ui.activeElement);
    }

    showNumbers() {
        this.hideNumbers();
        this.targets = collectTargets(this.services.ui.activeElement);
        this.state.numbers = this.targets.map(({ el }, index) => {
            const rect = el.getBoundingClientRect();
            return { n: index + 1, top: rect.top, left: rect.left };
        });
        window.addEventListener("scroll", this.hideNumbers, {
            capture: true,
            once: true,
        });
        window.addEventListener("resize", this.hideNumbers, { once: true });
    }

    hideNumbers() {
        window.removeEventListener("scroll", this.hideNumbers, { capture: true });
        window.removeEventListener("resize", this.hideNumbers);
        this.targets = [];
        this.state.numbers = [];
    }

    /** @param {Proposal} proposal */
    async run(proposal) {
        this.state.busy = true;
        try {
            const undo = await execute(proposal, {
                services: this.services,
                submit: (text) => this.submit(text),
                undo: () => this.undo(),
                showHelp: () => {
                    this.state.help = true;
                },
                showNumbers: () => this.showNumbers(),
                hideNumbers: () => this.hideNumbers(),
                targetView: (target) => targetView(this.services, target),
                getService: (name) => this.allServices[name],
                startSession: (session) => this.startSession(session),
                report: (message) => {
                    this.state.message = message;
                },
            });
            if (proposal.kind !== "show_numbers") {
                this.hideNumbers();
            }
            if (proposal.kind !== "undo" && proposal.kind !== "help") {
                this.state.done = [
                    {
                        description: proposal.description,
                        undo,
                        fromModel: Boolean(proposal.fromModel),
                    },
                    ...this.state.done,
                ].slice(0, MAX_DONE);
            }
        } catch (error) {
            this.state.message = /** @type {Error} */ (error).message;
        } finally {
            this.state.busy = false;
        }
    }

    async confirm() {
        const proposal = toRaw(this.state.pending);
        this.state.pending = null;
        if (proposal) {
            await this.run(proposal);
        }
    }

    /** @param {number} index */
    async pick(index) {
        const proposal = toRaw(this.state.candidates[index]);
        this.state.candidates = [];
        if (proposal) {
            await this.propose(proposal);
        }
    }

    async undo() {
        const index = this.state.done.findIndex((done) => done.undo);
        if (index === -1) {
            this.state.message = _t("There is nothing to undo.");
            return;
        }
        const [done] = this.state.done.splice(index, 1);
        await done.undo?.();
    }

    /** @param {{ label: string, stop: () => Promise<any> }} session */
    startSession({ label, stop }) {
        this.stopCurrentSession = stop;
        this.state.session = { label, stopping: false };
    }

    async stopSession() {
        const stop = this.stopCurrentSession;
        if (!stop || !this.state.session) {
            return;
        }
        this.state.session.stopping = true;
        try {
            await stop();
        } finally {
            this.stopCurrentSession = null;
            this.state.session = null;
        }
    }

    async listen() {
        if (this.state.session) {
            await this.stopSession();
            return;
        }
        if (this.state.listening) {
            this.stop();
            return;
        }
        this.clear();
        this.state.open = true;
        const lang = speechLang();
        const engine = await firstAvailableEngine(lang);
        if (!engine) {
            this.state.message = _t(
                "No speech engine is available here. You can still type what you would say in the command palette, after “>”.",
            );
            return;
        }
        if (!(await this.acknowledged(engine.privacy()))) {
            return;
        }
        this.abort = new AbortController();
        Object.assign(this.state, { listening: true, heard: "", interim: "" });
        let text = "";
        try {
            text = await engine.listen({
                lang,
                phrases: this.phrases(),
                onInterim: (interim) => {
                    this.state.interim = interim;
                },
                signal: this.abort.signal,
            });
        } catch (error) {
            this.state.message = /** @type {Error} */ (error).message;
        } finally {
            this.state.listening = false;
            this.abort = null;
        }
        if (text.trim()) {
            await this.submit(text);
        } else if (!this.state.message) {
            this.state.message = _t("Nothing was heard.");
        }
    }

    stop() {
        this.abort?.abort();
    }

    /**
     * @param {string} privacy
     * @returns {Promise<boolean>}
     */
    acknowledged(privacy) {
        if (user.settings?.voice_notice_acknowledged) {
            return Promise.resolve(true);
        }
        this.state.notice = privacy;
        return new Promise((resolve) => {
            this.acknowledge = (accepted) => {
                this.state.notice = "";
                this.acknowledge = null;
                if (accepted) {
                    user.setUserSettings("voice_notice_acknowledged", true);
                }
                resolve(accepted);
            };
        });
    }
}

export const voiceService = {
    dependencies: [
        "action",
        "active_view",
        "command",
        "home_menu",
        "hotkey",
        "menu",
        "orm",
        "ui",
    ],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {Record<string, any>} services
     */
    start(env, services) {
        return new VoiceService(services, env.services);
    },
};

registry.category("services").add("voice", voiceService);
