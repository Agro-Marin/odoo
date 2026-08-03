// @ts-check
/** @odoo-module native */

/** @module @web/fields/translation_button */

import { Component } from "@odoo/owl";
import { localization } from "@web/core/l10n/localization";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { useOwnedDialogs } from "@web/core/utils/hooks";
import { RelationalRecord } from "@web/model/relational_model/record";

import { TranslationDialog } from "./translation_dialog.js";

/** @type {{ code: string | undefined, language: string }} */
const _langCache = { code: undefined, language: "" };

/**
 * @returns {(params: { record: Object, fieldName: string }) => Promise<void>}
 */
export function useTranslationDialog() {
    const addDialog = useOwnedDialogs();

    /** @param {{ record: any, fieldName: string }} param0 */
    async function openTranslationDialog({ record, fieldName }) {
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
        const { record } = this.props;
        return !(
            record.isNew &&
            record.model.root instanceof RelationalRecord &&
            record.model.root !== record
        );
    }
    /** @returns {string} */
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
