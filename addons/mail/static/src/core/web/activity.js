/** @odoo-module native */
import { useAttachmentUploader } from "@mail/core/common/attachment_uploader_hook";
import { discussComponentRegistry } from "@mail/core/common/discuss_component_registry";
import { ActivityMailTemplate } from "@mail/core/web/activity_mail_template";
import { ActivityMarkAsDone } from "@mail/core/web/activity_markasdone_popover";
import { computeDelay, getMsToTomorrow } from "@mail/utils/common/dates";
import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { FileUploader } from "@web/core/file_upload/file_handler";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { usePopover } from "@web/ui/popover/popover_hook";
/**
 * @typedef {Object} Props
 * @property {import("models").Activity} activity
 * @property {function} onActivityChanged
 * @property {function} reloadParentView
 * @extends {Component<Props, Env>}
 */
export class Activity extends Component {
    static components = { ActivityMailTemplate, FileUploader };
    static props = ["activity", "onActivityChanged", "reloadParentView"];
    static template = "mail.Activity";

    setup() {
        super.setup();
        this.storeService = useService("mail.store");
        this.state = useState({ showDetails: false });
        this.markDonePopover = usePopover(ActivityMarkAsDone, { position: "right" });
        // Registered by the discuss web layer, which is always bundled with
        // core/web (backend assets).
        this.avatarCard = usePopover(discussComponentRegistry.get("AvatarCardPopover"));
        onMounted(() => {
            this.updateDelayAtNight();
        });
        onWillUnmount(() => browser.clearTimeout(this.updateDelayMidnightTimeout));
        this.attachmentUploader = useAttachmentUploader(this.thread);
    }

    get displayName() {
        if (this.props.activity.summary) {
            return _t("“%s”", this.props.activity.summary);
        }
        return this.props.activity.display_name;
    }

    updateDelayAtNight() {
        browser.clearTimeout(this.updateDelayMidnightTimeout);
        this.updateDelayMidnightTimeout = browser.setTimeout(
            () => this.render(),
            getMsToTomorrow() + 100,
        ); // Make sure there is no race condition
    }

    get delay() {
        return computeDelay(this.props.activity.date_deadline);
    }

    toggleDetails() {
        this.state.showDetails = !this.state.showDetails;
    }

    async onClickMarkAsDone(ev) {
        if (this.markDonePopover.isOpen) {
            this.markDonePopover.close();
            return;
        }
        this.markDonePopover.open(ev.currentTarget, {
            activity: this.props.activity,
            hasHeader: true,
            onActivityChanged: this.props.onActivityChanged,
        });
    }

    async onFileUploaded(data) {
        const thread = this.thread;
        const { id: attachmentId } = await this.attachmentUploader.uploadData(data, {
            activity: this.props.activity,
        });
        await this.props.activity.markAsDone([attachmentId]);
        this.props.onActivityChanged(thread);
        await thread.fetchNewMessages();
    }

    onClickAvatar(ev) {
        if (!this.props.activity.user_id) {
            return;
        }
        const target = ev.currentTarget;
        if (!this.avatarCard.isOpen) {
            this.avatarCard.open(target, {
                id: this.props.activity.user_id.id,
            });
        }
    }

    async edit() {
        const thread = this.thread;
        await this.props.activity.edit();
        this.props.onActivityChanged(thread);
    }

    async unlink() {
        const thread = this.thread;
        const { activity } = this.props;
        // server first: the local remove() broadcasts the deletion to every
        // tab and has no rollback — removing before the RPC made a failed
        // unlink (access error, network) vanish the activity everywhere
        // while it still exists server-side
        await this.env.services.orm.unlink("mail.activity", [activity.id]);
        activity.remove();
        this.props.onActivityChanged(thread);
    }

    get thread() {
        return this.env.services["mail.store"].Thread.insert({
            model: this.props.activity.res_model,
            id: this.props.activity.res_id,
        });
    }

    /**
     * @param {MouseEvent} ev
     */
    async onClick(ev) {
        this.storeService.handleClickOnLink(ev, this.thread);
    }
}
