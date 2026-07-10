// @ts-check
/** @odoo-module native */

/** @module @web/fields/translation_button - Translation button component and useTranslationDialog hook for translatable fields */

import { Component } from "@odoo/owl";
import { localization } from "@web/core/l10n/localization";
import { _t } from "@web/core/l10n/translation";
import { useOwnedDialogs } from "@web/core/utils/hooks";
import { RelationalRecord } from "@web/model/relational_model/record";
import { user } from "@web/services/user";

import { TranslationDialog } from "./translation_dialog.js";

// Lazy module-level memo: ``new Intl.Locale`` per render is measurable on
// list views with many translatable cells; ``user.lang`` is keyed to stay
// correct across test environments that swap the user.
const _langCache = { code: undefined, language: "" };

/**
 * Prepares a function that opens the dialog to edit a field's translation
 * values. Factored out of legacy_fields for reuse until folded into
 * TranslationButton.
 *
 * @returns {(params: { record: Object, fieldName: string }) => Promise<void>}
 */
export function useTranslationDialog() {
    const addDialog = useOwnedDialogs();

    async function openTranslationDialog({ record, fieldName }) {
        // in case of DynamicList list views model.root won't be a RelationalRecord but a DynamicList itself
        const saved =
            record.model.root instanceof RelationalRecord
                ? await record.model.root.save()
                : await record.save();
        if (!saved) {
            return;
        }
        const { resModel, resId } = record;

        addDialog(TranslationDialog, {
            fieldName: fieldName,
            resId: resId,
            resModel: resModel,
            userLanguageValue: record.data[fieldName] || "",
            isComingFromTranslationAlert: false,
            onSave: async () => {
                await record.load();
            },
        });
    }

    return openTranslationDialog;
}

export class TranslationButton extends Component {
    static template = "web.TranslationButton";
    static props = {
        fieldName: { type: String },
        record: { type: Object },
    };

    setup() {
        this.translationDialog = useTranslationDialog();
    }

    buttonClasses() {
        return !this.isClickable ? { "text-muted": true } : undefined;
    }
    buttonTooltip() {
        return !this.isClickable
            ? _t("Save this record and its parent to translate")
            : undefined;
    }

    /** @returns {boolean} */
    get isMultiLang() {
        return localization.multiLang;
    }
    get isClickable() {
        // a new record still created inside an x2many has no id of its own to translate
        const { record } = this.props;
        return !(
            record.isNew &&
            record.model.root instanceof RelationalRecord &&
            record.model.root !== record
        );
    }
    /** @returns {string} Uppercase language code (e.g. "EN") */
    get lang() {
        if (_langCache.code !== user.lang) {
            _langCache.code = user.lang;
            _langCache.language = new Intl.Locale(user.lang).language.toUpperCase();
        }
        return _langCache.language;
    }

    onClick() {
        if (!this.isClickable) {
            return;
        }
        const { fieldName, record } = this.props;
        this.translationDialog({ fieldName, record });
    }
}
