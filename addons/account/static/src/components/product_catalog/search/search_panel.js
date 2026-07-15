/** @odoo-module native */
import { _t } from "@web/core/l10n/translation";
import { onWillStart, useState } from '@odoo/owl';
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { rpc } from '@web/core/network/rpc';
import { useBus, useService } from '@web/core/utils/hooks';
import { SearchPanel } from '@web/search/search_panel/search_panel';


export class AccountProductCatalogSearchPanel extends SearchPanel {
    static template = 'account.ProductCatalogSearchPanel';

    setup() {
        super.setup();

        this.notification = useService("notification");
        this.state = useState({
            ...this.state,
            sections: new Map(),
            isAddingSection: '',
            newSectionName: "",
        });

        useBus(this.env.searchModel, 'section-line-count-change', this.updateSectionLineCount);

        onWillStart(async () => await this.loadSections());
    }

    /**
     * Safety net for the section RPC operations: never let a rejected request
     * become a silent unhandled rejection. Log it and tell the user.
     * @param {Error} error
     */
    _notifySectionError(error) {
        console.error("[product_catalog] section operation failed:", error);
        this.notification.add(_t("The sections could not be updated. Please retry."), {
            type: "danger",
        });
    }

    updateActiveValues() {
        super.updateActiveValues();
        this.state.sidebarExpanded ||= this.showSections;
    }

    get showSections() {
        return this.env.model.config.context.show_sections;
    }

    get selectedSection() {
        return this.env.searchModel.selectedSection;
    }

    onDragStart(sectionId, ev) {
        ev.dataTransfer.setData('section_id', sectionId);
    }

    onDragOver(ev) {
        ev.preventDefault();
    }

    onDrop(targetSecId, ev) {
        ev.preventDefault();
        const moveSecId = parseInt(ev.dataTransfer.getData('section_id'));
        if (moveSecId !== targetSecId) this.reorderSections(moveSecId, targetSecId);
    }

    enableSectionInput(isAddingSection) {
        this.state.isAddingSection = isAddingSection;
        setTimeout(() => document.querySelector('.o_section_input')?.focus(), 100);
    }

    onSectionInputKeydown(ev) {
        const hotkey = getActiveHotkey(ev);
        if (hotkey === 'enter') {
            this.createSection();
        } else if (hotkey === 'escape') {
            Object.assign(this.state, {
                isAddingSection: '',
                newSectionName: "",
            });
        }
    }

    setSelectedSection(sectionId=null, filtered=false) {
        this.env.searchModel.setSelectedSection(sectionId, filtered);
    }

    async createSection() {
        const sectionName = this.state.newSectionName.trim();
        const position = this.state.isAddingSection;
        // Capture the input then clear it synchronously, so a concurrent trigger
        // (Enter + blur, or a double Enter) can't fire a second create RPC with the
        // same name before this one resolves.
        Object.assign(this.state, {
            isAddingSection: '',
            newSectionName: "",
        });
        if (!sectionName) {
            return;
        }

        try {
            const section = await rpc('/product/catalog/create_section',
                this._getSectionInfoParams({
                    name: sectionName,
                    position: position,
                })
            );

            if (section) {
                const sections = this.state.sections;
                let newLineCount = 0;

                if (position === 'top') {
                    newLineCount = sections.get(false).line_count;
                    sections.delete(false);
                }
                sections.set(section.id, {
                    name: sectionName,
                    sequence: section.sequence,
                    line_count: newLineCount,
                });
                this._sortSectionsBySequence(sections);
                this.setSelectedSection(section.id);
            }
        } catch (error) {
            this._notifySectionError(error);
        }
    }

    async loadSections() {
        if (!this.showSections) return;
        let sections;
        try {
            sections = await rpc('/product/catalog/get_sections', this._getSectionInfoParams());
        } catch (error) {
            this._notifySectionError(error);
            return;
        }

        const sectionMap = new Map();
        for (const {id, name, sequence, line_count} of sections) {
            sectionMap.set(id, {name, sequence, line_count});
        }
        this.state.sections = sectionMap;
        this.setSelectedSection(sectionMap.size > 0 ? [...sectionMap.keys()][0] : null);
    }

    async reorderSections(moveId, targetId) {
        const sections = this.state.sections;
        const moveSection = sections.get(moveId);
        const targetSection = sections.get(targetId);

        if (!moveSection || !targetSection) return;

        let updatedSequences;
        try {
            updatedSequences = await rpc('/product/catalog/resequence_sections',
                this._getSectionInfoParams({
                    sections: [
                        { id: moveId, sequence: moveSection.sequence },
                        { id: targetId, sequence: targetSection.sequence },
                    ],
                })
            );
        } catch (error) {
            // Nothing was mutated locally yet (the sequence swap happens below on
            // success), so resyncing from the server keeps the sidebar consistent.
            this._notifySectionError(error);
            await this.loadSections();
            return;
        }
        for (const [id, sequence] of Object.entries(updatedSequences)) {
            const section = sections.get(parseInt(id));
            section && (section.sequence = sequence);
        }
        const noSection = sections.get(false);
        noSection && (noSection.sequence = 0); // Reset the sequence of the "No Section"
        this._sortSectionsBySequence(sections);
    }

    updateSectionLineCount({detail: {sectionId, lineCountChange}}) {
        const sections = this.state.sections;
        const section = sections.get(sectionId);
        if (!section) return;

        section.line_count = Math.max(0, section.line_count + lineCountChange);

        if (section.line_count === 0 && sectionId === false && sections.size > 1) {
            sections.delete(sectionId);
            this.setSelectedSection(sections.size > 0 ? [...sections.keys()][0] : null);
        }
    }

    _getSectionInfoParams(extra = {}) {
        const ctx = this.env.model.config.context;
        return {
            res_model: ctx.product_catalog_order_model,
            order_id: ctx.order_id,
            child_field: ctx.child_field,
            ...extra,
        };
    }

    _sortSectionsBySequence(sections) {
        this.state.sections = new Map(
            [...sections].sort((a, b) => a[1].sequence - b[1].sequence)
        );
    }
}
