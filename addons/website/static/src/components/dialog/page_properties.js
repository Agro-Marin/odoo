/** @odoo-module native */
import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { sprintf } from "@web/core/utils/format/strings";
import { useAutofocus, useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { usePopover } from "@web/ui/popover";
import { FormController, formView } from "@web/views/form";
import { FormViewDialog } from "@web/views/view_dialogs";

import { WebsiteDialog } from "./dialog.js";

const log = makeLogger("website.dialog.page_properties");

class PageDependenciesPopover extends Component {
    static template = "website.PageDependencies.Tooltip";
    static props = {
        dependencies: { type: Object },
        close: { type: Function, optional: true },
    };
}

export class PageDependencies extends Component {
    static template = "website.PageDependencies";
    static props = {
        resIds: Array,
        resModel: String,
        mode: String,
    };

    setup() {
        super.setup();
        useLifecycleLog(log);
        this.orm = useService("orm");

        this.action = useRef("action");
        this.sprintf = sprintf;
        this.dependenciesPopover = usePopover(PageDependenciesPopover, {
            position: "right",
            class: "o_page_dependencies",
        });

        useEffect(
            () => {
                this.fetchDependencies();
            },
            () => [],
        );
        this.state = useState({
            dependencies: {},
        });
    }

    async getResIds() {
        return this.props.resIds;
    }

    async fetchDependencies() {
        const endFetch = log.perf("PageDependencies search_url_dependencies", () => ({
            resModel: this.props.resModel,
        }));
        this.state.dependencies = await this.orm.call(
            "website",
            "search_url_dependencies",
            [this.props.resModel, await this.getResIds()],
        );
        endFetch();
    }

    showDependencies() {
        log.lifecycle("PageDependencies open popover");
        this.dependenciesPopover.open(this.action.el, {
            dependencies: this.state.dependencies,
        });
    }
}

export class FormPageDependencies extends PageDependencies {
    static props = {
        ...standardFieldProps,
        ...PageDependencies.props,
        resIds: { type: Array, optional: true },
    };

    async getResIds() {
        const endRead = log.perf("FormPageDependencies read target_model_id", () => ({
            resModel: this.props.record.resModel,
            resId: this.props.record.resId,
        }));
        const records = await this.orm.read(
            this.props.record.resModel,
            [this.props.record.resId],
            ["target_model_id"],
        );
        endRead(() => ({ records: records.length }));
        return records.map((record) => record.target_model_id[0]);
    }
}

export const formPageDependenciesWidget = {
    component: FormPageDependencies,
    extractProps: ({ attrs }) => {
        const { mode, name, resModel, resIds } = attrs;
        return {
            mode,
            name: name || "",
            resModel,
            resIds,
        };
    },
};
registry
    .category("view_widgets")
    .add("form_page_dependencies", formPageDependenciesWidget);

export class DeletePageDialog extends Component {
    static template = "website.DeletePageDialog";
    static components = {
        PageDependencies,
        CheckBox,
        WebsiteDialog,
    };
    static props = {
        resIds: Array,
        resModel: String,
        onDelete: { type: Function, optional: true },
        close: Function,
        hasNewPageTemplate: { type: Boolean, optional: true },
    };

    setup() {
        useLifecycleLog(log);
        this.website = useService("website");

        this.state = useState({
            confirm: false,
        });
    }

    onConfirmCheckboxChange(checked) {
        this.state.confirm = checked;
    }

    onClickDelete() {
        log.logic("DeletePageDialog confirmed", () => ({
            resModel: this.props.resModel,
            resIds: this.props.resIds,
        }));
        this.props.close();
        this.props.onDelete();
    }
}

export class DuplicatePageDialog extends Component {
    static components = { WebsiteDialog };
    static template = "website.DuplicatePageDialog";
    static props = {
        onDuplicate: Function,
        close: Function,
        pageIds: { type: Array, element: Number },
    };

    setup() {
        useLifecycleLog(log);
        this.orm = useService("orm");
        this.website = useService("website");
        useAutofocus();

        this.state = useState({
            name: "",
        });
    }

    async duplicate() {
        const duplicates = [];
        log.logic("DuplicatePageDialog duplicate", () => ({
            hasName: Boolean(this.state.name),
            pages: this.props.pageIds.length,
        }));
        const endClone = log.perf("DuplicatePageDialog clone_page loop");
        if (this.state.name) {
            for (let count = 0; count < this.props.pageIds.length; count++) {
                const name = this.state.name + (count ? ` ${count + 1}` : "");
                duplicates.push(
                    await this.orm.call("website.page", "clone_page", [
                        this.props.pageIds[count],
                        name,
                    ]),
                );
            }
        }
        endClone(() => ({ duplicates: duplicates.length }));
        this.props.onDuplicate(duplicates);
    }
}

export class PagePropertiesFormController extends FormController {
    static props = {
        ...FormController.props,
        clonePage: { type: Function, optional: true },
        deletePage: { type: Function, optional: true },
    };
}

registry.category("views").add("page_properties_dialog_form", {
    ...formView,
    Controller: PagePropertiesFormController,
});

export class PagePropertiesDialog extends FormViewDialog {
    static props = {
        ...FormViewDialog.props,
        onClose: { type: Function, optional: true },
        resModel: { type: String, optional: true },
    };

    static defaultProps = {
        ...FormViewDialog.defaultProps,
        title: _t("Page Properties"),
        size: "md",
        onClose: () => {},
    };

    setup() {
        super.setup();
        useLifecycleLog(log);
        this.dialog = useService("dialog");
        this.orm = useService("orm");
        this.website = useService("website");
        log.logic("PagePropertiesDialog form variant", () => ({
            isPage: this.isPage,
            targetModel: this.targetModel,
            resId: this.resId,
        }));

        this.viewProps = {
            ...this.viewProps,
            resId: this.resId,
            resModel: this.resModel,
            context: Object.assign(
                {
                    form_view_ref: this.isPage
                        ? "website.website_page_properties_view_form"
                        : "website.website_page_properties_base_view_form",
                },
                this.viewProps.context,
            ),
            ...(this.isPage
                ? {
                      buttonTemplate: "website.PagePropertiesDialogButtons",
                      clonePage: this.clonePage.bind(this),
                      deletePage: this.deletePage.bind(this),
                  }
                : {}),
        };
    }

    get resId() {
        return this.props.resId;
    }

    get resModel() {
        if (this.props.resModel) {
            return this.props.resModel;
        }
        return this.isPage ? "website.page.properties" : "website.page.properties.base";
    }

    get targetId() {
        return this.website.currentWebsite?.metadata.mainObject.id;
    }

    get targetModel() {
        return this.website.currentWebsite?.metadata.mainObject.model;
    }

    get isPage() {
        return this.targetModel === "website.page";
    }

    clonePage() {
        log.logic("PagePropertiesDialog clonePage", () => ({
            targetId: this.targetId,
        }));
        this.dialog.add(DuplicatePageDialog, {
            pageIds: [this.targetId],
            onDuplicate: (duplicates) => {
                log.pipeline("PagePropertiesDialog duplicated: go to copy", () => ({
                    path: duplicates[0],
                }));
                this.props.close();
                this.props.onClose();
                this.website.goToWebsite({ path: duplicates[0], edition: true });
            },
        });
    }

    async deletePage() {
        const pageIds = [this.targetId];
        const endRead = log.perf("PagePropertiesDialog read is_new_page_template", {
            pageIds,
        });
        const newPageTemplateFields = await this.orm.read("website.page", pageIds, [
            "is_new_page_template",
        ]);
        endRead();
        this.dialog.add(DeletePageDialog, {
            resIds: pageIds,
            resModel: "website.page",
            onDelete: async () => {
                const endUnlink = log.perf("PagePropertiesDialog unlink page", {
                    pageIds,
                });
                await this.orm.unlink("website.page", pageIds);
                endUnlink();
                this.website.goToWebsite({ path: "/" });
                this.props.close();
                this.props.onClose();
            },
            hasNewPageTemplate: newPageTemplateFields[0].is_new_page_template,
        });
    }
}
