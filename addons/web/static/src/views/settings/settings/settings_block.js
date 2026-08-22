// @ts-check
/** @odoo-module native */

import {
    Component,
    onWillRender,
    useChildSubEnv,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { normalizedMatch } from "@web/core/l10n/utils";
import { HighlightText } from "@web/views/settings/highlight_text/highlight_text";

export class SettingsBlock extends Component {
    static template = "web.SettingsBlock";
    static components = {
        HighlightText,
    };
    static props = {
        title: { type: String, optional: true },
        tip: { type: String, optional: true },
        slots: { type: Object, optional: true },
        class: { type: String, optional: true },
    };
    /** @type {import("@odoo/owl").Ref} */
    settingsContainerRef;
    /** @type {import("@odoo/owl").Ref} */
    settingsContainerTipRef;
    /** @type {import("@odoo/owl").Ref} */
    settingsContainerTitleRef;
    /** @type {{ showAllContainer: boolean }} */
    showAllContainerState;
    /** @type {{ search: any }} */
    state;

    setup() {
        this.state = useState({
            search: this.env.searchState,
        });
        this.showAllContainerState = useState({
            showAllContainer: false,
        });
        useChildSubEnv({
            showAllContainer: this.showAllContainerState,
        });
        this.settingsContainerRef = useRef("settingsContainer");
        this.settingsContainerTitleRef = useRef("settingsContainerTitle");
        this.settingsContainerTipRef = useRef("settingsContainerTip");
        useEffect(
            () => {
                const container = this.settingsContainerRef.el;
                if (!container) {
                    return;
                }
                const force =
                    this.state.search.value &&
                    !this.matchesTitleOrTip() &&
                    !container.querySelector(".o_setting_box.o_searchable_setting");
                this.toggleContainer(force);
            },
            () => [this.state.search.value],
        );
        onWillRender(() => {
            this.showAllContainerState.showAllContainer = this.matchesTitleOrTip();
        });
    }
    /**
     * @returns {boolean}
     */
    matchesTitleOrTip() {
        const searchValue = this.state.search.value;
        const blockText = [this.props.title, this.props.tip].join();
        return normalizedMatch(blockText, searchValue).start !== -1;
    }
    /**
     * @param {boolean} force
     */
    toggleContainer(force) {
        if (this.settingsContainerTitleRef.el) {
            this.settingsContainerTitleRef.el.classList.toggle("d-none", force);
        }
        if (this.settingsContainerTipRef.el) {
            this.settingsContainerTipRef.el.classList.toggle("d-none", force);
        }
        this.settingsContainerRef.el?.classList.toggle("d-none", force);
    }
}
