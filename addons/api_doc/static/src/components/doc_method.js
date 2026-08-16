/** @odoo-module native */
import { DocRequest } from "@api_doc/components/doc_request";
import { DocTable, TABLE_TYPES } from "@api_doc/components/doc_table";
import { getParameterDefaultValue } from "@api_doc/utils/doc_model_utils";
import { useDocUI } from "@api_doc/utils/doc_ui_store";
import { Component, markup, useState } from "@odoo/owl";

export class DocMethod extends Component {
    static template = "api_doc.DocMethod";
    static components = {
        DocRequest,
        DocTable,
    };
    static props = {
        method: Object,
        class: String,
    };

    setup() {
        this.ui = useDocUI();
        this.state = useState({ open: true });
        this.parametersData = {
            headers: ["Name", "Type", "Default Value", "Description"],
            items: Object.entries(this.method.parameters).map(([name, options]) => [
                { type: TABLE_TYPES.Code, value: name },
                {
                    type: TABLE_TYPES.Code,
                    value: "annotation" in options ? options.annotation : "-",
                },
                { type: TABLE_TYPES.Code, value: this.getDefaultValue(options) },
                {
                    type: TABLE_TYPES.Tooltip,
                    value: options.doc ? markup(options.doc) : "",
                },
            ]),
        };
    }

    get method() {
        return this.props.method;
    }

    get doc() {
        return this.method.doc;
    }

    get isVertical() {
        return this.ui.size < 1400;
    }

    getDefaultValue(param) {
        if ("default" in param) {
            return typeof param.default === "string"
                ? `"${param.default}"`
                : param.default;
        } else {
            return "-";
        }
    }

    get request() {
        if (this.method.request) {
            return this.method.request;
        }

        const request = {
            ids: [],
            context: {},
        };

        // `api` holds "model" and/or "readonly". Testing it for truthiness
        // dropped `ids` from readonly INSTANCE methods too -- web_read and
        // friends -- whose call then silently ran against no records at all.
        if (this.method.api?.includes("model")) {
            delete request.ids;
        }

        for (const paramName in this.method.parameters) {
            const param = this.method.parameters[paramName];
            // *args / **kwargs are not parameters a caller sends by name: the
            // extra values go in as keys of their own.
            if (param.kind === "VAR_POSITIONAL" || param.kind === "VAR_KEYWORD") {
                continue;
            }
            request[paramName] = getParameterDefaultValue(paramName, param);
        }

        return request;
    }
}
