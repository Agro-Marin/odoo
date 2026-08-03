// @ts-check
/** @odoo-module native */

/** @module @web/fields/translation_dialog */

import { Component, onWillStart } from "@odoo/owl";
import { jsToPyLocale } from "@web/core/l10n/utils";
import { _t, loadLanguages } from "@web/core/translation";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog/dialog";

export class TranslationDialog extends Component {
    static template = "web.TranslationDialog";
    static components = { Dialog };
    static props = {
        fieldName: String,
        resId: Number,
        resModel: String,
        userLanguageValue: { type: String, optional: true },
        isComingFromTranslationAlert: { type: Boolean, optional: true },
        onSave: Function,
        close: Function,
        isText: { type: Boolean, optional: true },
        showSource: { type: Boolean, optional: true },
    };
    setup() {
        super.setup();
        this.title = _t("Translate: %s", this.props.fieldName);

        this.user = user;
        this.userPyLang = jsToPyLocale(user.lang);
        this.orm = useService("orm");

        this.terms = [];
        this.updatedTerms = {};
        this.isText = this.props.isText ?? false;
        this.showSource = this.props.showSource ?? false;

        onWillStart(async () => {
            const languages = await loadLanguages(this.orm);
            const [translations, context] = await this.loadTranslations();
            let id = 1;
            translations.forEach((t) => (t.id = id++));
            this.isText = context.translation_type === "text";
            this.showSource = context.translation_show_source;

            this.terms = translations.map((term) => {
                const relatedLanguage = languages.find((l) => l[0] === term.lang);
                const termInfo = {
                    ...term,
                    langName: relatedLanguage ? relatedLanguage[1] : term.lang,
                    value: term.value || "",
                };
                if (
                    term.lang === this.userPyLang &&
                    !this.showSource &&
                    !this.props.isComingFromTranslationAlert
                ) {
                    this.updatedTerms[term.id] = this.props.userLanguageValue;
                    termInfo.value = this.props.userLanguageValue;
                }
                return termInfo;
            });
            this.terms.sort((a, b) => a.langName.localeCompare(b.langName));
        });
    }

    async loadTranslations() {
        return this.orm.call(this.props.resModel, "get_field_translations", [
            [this.props.resId],
            this.props.fieldName,
        ]);
    }

    async onSave() {
        const translations = {};

        this.terms.map((term) => {
            const updatedTermValue = this.updatedTerms[term.id];
            if (term.id in this.updatedTerms && term.value !== updatedTermValue) {
                if (this.showSource) {
                    if (!translations[term.lang]) {
                        translations[term.lang] = {};
                    }
                    translations[term.lang][term.source] =
                        updatedTermValue || term.source;
                } else {
                    translations[term.lang] = updatedTermValue || false;
                }
            }
        });

        await this.orm.call(this.props.resModel, "update_field_translations", [
            [this.props.resId],
            this.props.fieldName,
            translations,
        ]);

        await this.props.onSave();
        this.props.close();
    }
}
