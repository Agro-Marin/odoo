/** @odoo-module native */
import { DocErrorDialog } from "@api_doc/components/doc_error_dialog";
import { ApiKeyModal } from "@api_doc/components/doc_modal_api_key";
import { SearchModal } from "@api_doc/components/doc_modal_search";
import { DocModel } from "@api_doc/components/doc_model";
import { DocSidebar } from "@api_doc/components/doc_sidebar";
import { ModelStore } from "@api_doc/doc_model_store";
import { useDocUI } from "@api_doc/utils/doc_ui_store";
import {
    Component,
    onMounted,
    useExternalListener,
    useState,
    useSubEnv,
} from "@odoo/owl";

export class DocClient extends Component {
    static template = "api_doc.DocClient";

    static components = {
        DocSidebar,
        DocModel,
        ApiKeyModal,
        SearchModal,
        DocErrorDialog,
    };
    static props = {};

    setup() {
        this.setTheme(localStorage.getItem("theme") || "odoo-dark");

        this.ui = useDocUI();
        this.modelStore = useState(new ModelStore());
        useSubEnv({ modelStore: this.modelStore });

        this.state = useState({ showSearchModal: false });

        onMounted(async () => {
            await this.modelStore.loadModels();
            this.selectUrlModel();
        });

        // useExternalListener rather than addEventListener: the raw listener
        // outlives the component and keeps it alive with it.
        useExternalListener(window, "popstate", () => {
            this.selectUrlModel();
        });
    }

    selectUrlModel() {
        const actives = {};
        const parts = window.location.pathname.split("/");
        const docIndex = parts.indexOf("doc");
        const urlModel = parts[docIndex + 1];
        if (urlModel) {
            const model = this.modelStore.getBasicModelData(urlModel);
            if (model) {
                actives.model = model;
            }
        }

        const hash = window.location.hash.substring(1);
        const model = actives.model;
        if (model && hash) {
            if (model.methods.includes(hash)) {
                actives.method = hash;
            } else if (model.fields[hash]) {
                actives.field = hash;
            }
        }

        this.modelStore.setActiveModel(actives);
    }

    toggleTheme() {
        this.setTheme(this.theme === "odoo-dark" ? "odoo-light" : "odoo-dark");
    }

    setTheme(theme) {
        this.theme = theme;
        localStorage.setItem("theme", theme);
        document.body.setAttribute("theme", theme);
    }
}
