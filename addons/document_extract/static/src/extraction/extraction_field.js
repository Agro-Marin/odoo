/** @odoo-module native */
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { standardFieldProps } from "@web/fields/standard_field_props";

const STATE_BADGES = {
    none: "text-bg-light",
    queued: "text-bg-secondary",
    running: "text-bg-info",
    waiting: "text-bg-info",
    done: "text-bg-success",
    partial: "text-bg-warning",
    failed: "text-bg-danger",
};

function readable(value) {
    if (value === null || value === undefined || value === false) {
        return "";
    }
    if (Array.isArray(value)) {
        return _t("%s entries", value.length);
    }
    if (typeof value === "object") {
        return JSON.stringify(value);
    }
    return String(value);
}

export class DocumentExtractionField extends FieldComponent {
    static template = "document_extract.ExtractionField";
    static props = { ...standardFieldProps };

    get state() {
        return this.props.record.data.extract_state || "none";
    }

    get stateBadge() {
        return STATE_BADGES[this.state] || "text-bg-light";
    }

    get stateLabel() {
        const definition = this.props.record.fields.extract_state;
        const option = (definition?.selection || []).find(
            ([value]) => value === this.state,
        );
        return option ? option[1] : this.state;
    }

    get error() {
        return this.props.record.data.extract_error || "";
    }

    get readings() {
        const result = this.field.value || {};
        return Object.keys(result)
            .sort()
            .map((name) => {
                const read = result[name];
                return {
                    name,
                    value: readable(read.value),
                    source: read.source || "",
                    confidence: this.asPercent(read.confidence),
                    disputed: Boolean(read.disputed),
                    rejected: (read.candidates || [])
                        .filter((candidate) => candidate.value !== read.value)
                        .map((candidate) => ({
                            value: readable(candidate.value),
                            source: candidate.source || "",
                            confidence: this.asPercent(candidate.confidence),
                        })),
                };
            });
    }

    get missingFields() {
        return this.props.record.data.extract_missing?.fields || [];
    }

    get brokenRules() {
        return this.props.record.data.extract_missing?.rules || [];
    }

    get corrections() {
        const stored = this.props.record.data.extract_corrections || {};
        return Object.keys(stored)
            .sort()
            .map((name) => ({
                name,
                read: readable(stored[name].read),
                readBy: stored[name].read_by || "",
                correctedTo: readable(stored[name].corrected_to),
            }));
    }

    get isEmpty() {
        return (
            this.state === "none" &&
            !this.readings.length &&
            !this.missingFields.length &&
            !this.brokenRules.length
        );
    }

    asPercent(confidence) {
        return typeof confidence === "number" ? Math.round(confidence * 100) : null;
    }
}

export const documentExtractionField = {
    component: DocumentExtractionField,
    displayName: _t("Document extraction"),
    supportedTypes: ["json"],
    fieldDependencies: [
        { name: "extract_state", type: "selection", readonly: true },
        { name: "extract_missing", type: "json", readonly: true },
        { name: "extract_corrections", type: "json", readonly: true },
        { name: "extract_error", type: "text", readonly: true },
    ],
};

registerField("document_extraction", documentExtractionField);
