/** @odoo-module native */
import { Component } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { rpc } from "@web/core/network";
import { useChildRef } from "@web/core/utils/hooks";
import { AutoCompleteWithPages } from "@website/components/autocomplete_with_pages/autocomplete_with_pages";

const log = makeLogger("website.component.url_autocomplete");

export class UrlAutoComplete extends Component {
    static props = {
        options: { type: Object },
        loadAnchors: { type: Function },
        targetDropdown: { type: HTMLElement },
    };
    static template = "website.UrlAutoComplete";
    static components = { AutoCompleteWithPages };

    setup() {
        useLifecycleLog(log);
        this.inputRef = useChildRef();
    }

    get dropdownClass() {
        const classList = [];
        for (const key in this.props.options?.classes) {
            classList.push(key, this.props.options.classes[key]);
        }
        return classList.join(" ");
    }

    get dropdownOptions() {
        const options = {};
        if (this.props.options?.position) {
            options.position = this.props.options?.position;
        }
        return options;
    }

    get sources() {
        return [
            {
                optionSlot: "option",
                options: async (term) => {
                    const makeItem = (item) => ({
                        cssClass: "ui-autocomplete-item",
                        label: item.label,
                        onSelect: this.onSelect.bind(this, item.value),
                    });

                    if (term[0] === "#") {
                        const endAnchors = log.perf("loadAnchors", { term });
                        const anchors = await this.props.loadAnchors(
                            term,
                            this.props.options && this.props.options.body,
                        );
                        endAnchors(() => ({ anchors: anchors.length }));
                        return anchors.map((anchor) =>
                            makeItem({ label: anchor, value: anchor }),
                        );
                    } else if (term.startsWith("http") || term.length === 0) {
                        log.logic("suggest skip: absolute or empty term", { term });
                        return [];
                    }
                    if (this.props.options.isDestroyed?.()) {
                        log.logic("suggest skip: autocomplete destroyed");
                        return [];
                    }
                    const endSuggest = log.perf("get_suggested_links", { term });
                    const res = await rpc("/website/get_suggested_links", {
                        needle: term,
                        limit: 15,
                    });
                    endSuggest();
                    const choices = [];
                    for (const page of res.matching_pages) {
                        choices.push(makeItem(page));
                    }
                    for (const other of res.others) {
                        if (other.values.length) {
                            choices.push({
                                cssClass: "ui-autocomplete-category",
                                data: { separator: true },
                                label: other.title,
                            });
                            for (const page of other.values) {
                                choices.push(makeItem(page));
                            }
                        }
                    }
                    log.pipeline("suggested links", () => ({
                        term,
                        pages: res.matching_pages.length,
                        groups: res.others.length,
                        choices: choices.length,
                    }));
                    return choices;
                },
            },
        ];
    }

    onSelect(value) {
        log.logic("onSelect", { value });
        this.inputRef.value = value;
        this.props.targetDropdown.value = value;
        this.props.options.urlChosen?.();
    }

    onInput({ inputValue }) {
        this.props.targetDropdown.value = inputValue;
    }
}
