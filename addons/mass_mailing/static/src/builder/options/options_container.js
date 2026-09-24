/** @odoo-module native */
import { useBuilderContext } from "@html_builder/core/builder_context";
import { OptionsContainer } from "@html_builder/sidebar/option_container";
import { useState } from "@odoo/owl";

export class OptionsContainerWithSnippetVersionControl extends OptionsContainer {
    static template = "mass_mailing.OptionsContainer";
    setup() {
        super.setup();
        this.builderContext = useBuilderContext();
        this.versionState = useState({
            isUpToDate:
                this.builderContext.editor.shared.versionControl.hasAccessToOutdatedEl(
                    this.props.editingElement,
                ),
        });
    }
    // Version control
    replaceElementWithNewVersion() {
        this.callOperation(() => {
            this.builderContext.editor.shared.versionControl.replaceWithNewVersion(
                this.props.editingElement,
            );
        });
    }
    accessOutdated() {
        this.builderContext.editor.shared.versionControl.giveAccessToOutdatedEl(
            this.props.editingElement,
        );
        this.versionState.isUpToDate = true;
    }
}
