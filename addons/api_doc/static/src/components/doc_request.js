/** @odoo-module native */
import { createRequestCode, LANGUAGES } from "@api_doc/utils/doc_code_gen";
import { Component, useState } from "@odoo/owl";
import { CodeEditor } from "@web/components/code_editor";
import { browser } from "@web/core/browser/browser";

class CopyableCodeEditor extends CodeEditor {
    static template = "api_doc.DocRequest.CodeEditor";

    copyToClipboard() {
        navigator?.clipboard?.writeText(this.aceEditor.getValue());
        this.state.copied = true;
        setTimeout(() => {
            this.state.copied = false;
        }, 1000);
    }
}

export class DocRequest extends Component {
    static template = "api_doc.DocRequest";

    static components = {
        CodeEditor: CopyableCodeEditor,
    };
    static props = {
        url: String,
        request: { optional: true },
        // the reflected method this request illustrates, passed by DocMethod
        method: { type: Object, optional: true },
    };

    setup() {
        this.maxLines = Infinity;
        this.LANGUAGES = LANGUAGES;
        this.state = useState({
            exampleLanguage: LANGUAGES.json,
            exampleCode: "",
            requestCode: this.createRequestCode(LANGUAGES.json),
            response: {},
            requestTab: 0,
            showTraceback: false,
        });
        this.selectLanguage(localStorage.getItem("doc/code-lang") || LANGUAGES.json);
    }

    selectLanguage(language) {
        localStorage.setItem("doc/code-lang", language);
        this.state.exampleLanguage = language;
        this.state.exampleCode = this.createRequestCode(language);
    }

    createRequestCode(language) {
        return createRequestCode({
            language,
            url: window.location.origin + this.props.url,
            apiKey: this.env.modelStore.apiKey,
            requestObj: this.props.request,
        });
    }

    get responseText() {
        const response = this.state.response;
        return response.error || response.body;
    }

    get hasResponse() {
        return this.state.response.error || this.state.response.body;
    }

    async execute() {
        this.state.response = {};
        const result = await this.env.modelStore.executeRequest(
            this.props.url,
            this.state.requestCode,
        );
        if (result) {
            this.state.response = result;
        }
    }

    toggleTraceback() {
        this.state.showTraceback = !this.state.showTraceback;
    }

    // `error` is an object only when the body parsed as JSON; a plain string is
    // what a proxy, or any non-JSON 500, gives us instead.
    get errorTitle() {
        const error = this.state.response.error;
        return typeof error === "string" ? error : (error?.title ?? "");
    }

    get errorTraceback() {
        const error = this.state.response.error;
        return typeof error === "string" ? "" : (error?.traceback ?? "");
    }

    onClickClipboard() {
        browser.navigator.clipboard.writeText(
            `Error ${this.state.response.status}:\n\n${this.errorTitle}\n\n${this.errorTraceback}`,
        );
    }
}
