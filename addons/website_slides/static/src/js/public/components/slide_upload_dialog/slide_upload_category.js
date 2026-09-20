/** @odoo-module native */
import { Component, onMounted, onWillStart, useState } from "@odoo/owl";
import { DropdownItem } from "@web/components/dropdown";
import { SelectMenu } from "@web/components/select_menu";
import { rpc } from "@web/core/network";
import { _t } from "@web/core/translation";
import { uniqueId } from "@web/core/utils/functions";
import { loadPDFJS } from "@web/core/utils/pdfjs";
import { getDataURLFromFile } from "@web/core/utils/urls";

import { SlideUploadSourceTypes } from "./slide_upload_source_types.js";

export class SlideUploadCategory extends Component {
    static components = { DropdownItem, SelectMenu, SlideUploadSourceTypes };
    static props = {
        alertMsg: { type: String, optional: true },
        channelId: Number,
        categoryId: { type: Number, optional: true },
        slideCategory: String,
        canPublish: Boolean,
        canUpload: Boolean,
        upload: Function,
        slots: Object,
    };
    static sourceSettings = {
        document: {
            sourceTypeLabel: _t("Document Source"),
            selectFileLabel: _t("Choose a PDF"),
            acceptedFiles: "application/pdf",
            urlInputLabel: _t("Document Link"),
            urlInputName: "document_google_url",
        },
        infographic: {
            sourceTypeLabel: _t("Image Source"),
            selectFileLabel: _t("Choose an Image"),
            acceptedFiles: "image/*",
            urlInputLabel: _t("Image Link"),
            urlInputName: "image_google_url",
        },
        video: {
            urlInputLabel: _t("Video Link"),
            urlInputName: "video_url",
        },
    };
    static template = "website_slides.SlideUploadCategory";

    setup() {
        this.sourceSettings = SlideUploadCategory.sourceSettings;
        this.state = useState({
            alert: {
                class: "",
                message: "",
                show: false,
            },
            form: {
                duration: null,
                isLoading: false,
                isLocalSource: true,
                slideImage: "/website_slides/static/src/img/document.png",
                slideName: "",
                wasValidated: false,
                url: "",
            },
            preview: {
                show: false,
                hideSlideVideoTitle: true,
                videoTitle: "",
            },
            choices: {
                categories: [],
                categoryId: "",
                tags: [],
                tagIds: [],
            },
        });
        this.canSubmitForm = false;
        this.defaultCategoryId = this.props.categoryId;
        this.file = {};
        this.isValidUrl = true;

        onWillStart(async () => {
            const categories = await this._fetch_choices("category", [
                ["channel_id", "=", this.props.channelId],
            ]);
            this.state.choices.categories = categories;
            this.state.choices.categoryId = this._getDefaultCategoryId();
            const tags = await this._fetch_choices("tag");
            this.state.choices.tags = tags;
        });

        onMounted(() => {
            if (this.props.alertMsg) {
                this._alertDisplay(this.props.alertMsg);
            }
        });
    }

    choiceExists(input, choices) {
        return choices.some(
            (choice) => input.toLowerCase() === choice.label.toLowerCase(),
        );
    }

    onCategorySelect(value) {
        this.state.choices.categoryId = value;
    }

    onClickCreateCategoryBtn(categoryName) {
        const tempId = uniqueId("temp");
        this.state.choices.categories.push({ value: tempId, label: categoryName });
        this.state.choices.categoryId = tempId;
    }

    onTagsSelect(values) {
        this.state.choices.tagIds = values;
    }

    onClickCreateTagBtn(tagName) {
        const tempId = uniqueId("temp");
        this.state.choices.tags.push({ value: tempId, label: tagName });
        this.state.choices.tagIds.push(tempId);
    }

    async onChangeFileInput(ev) {
        this._alertRemove();

        const preventOnchange = ev.currentTarget.dataset.preventOnchange;

        const file = ev.target.files[0];
        if (!file) {
            this.state.form.slideImage = "/website_slides/static/src/img/document.png";
            this.state.preview.show = false;
            return;
        }
        const isImage = /^image\/.*/.test(file.type);
        this.file.name = file.name;
        this.file.type = file.type;
        if (!isImage && this.file.type !== "application/pdf") {
            this._alertDisplay(
                _t("Invalid file type. Please select pdf or image file"),
            );
            this._fileReset();
            this.state.preview.show = false;
            return;
        }
        if (file.size > 25 * 1024 * 1024) {
            this._alertDisplay(_t("File is too big. File size cannot exceed 25MB"));
            this._fileReset();
            this.state.preview.show = false;
            return;
        }

        if (file.type !== "application/pdf") {
            const dataURL = await getDataURLFromFile(file);
            if (isImage) {
                this.state.form.slideImage = dataURL;
            }
            this.file.data = dataURL.split(",", 2)[1];
            this.state.preview.show = true;
        } else {
            this.canSubmitForm = false;
            const dataURL = await getDataURLFromFile(file);
            this.file.data = dataURL.split(",", 2)[1];
            const pdfjsLib = await loadPDFJS();
            const pdfTask = pdfjsLib.getDocument({ data: atob(this.file.data) });
            pdfTask.onPassword = () => {
                this._alertDisplay(_t("You can not upload password protected file."));
                this._fileReset();
                this.canSubmitForm = true;
            };
            const pdf = await pdfTask.promise;

            this.state.form.duration = (pdf.numPages || 0) * 5;
            const page = await pdf.getPage(1);
            const viewport = page.getViewport({ scale: 1 });
            const canvas = document.getElementById("data_canvas");
            const context = canvas.getContext("2d");
            canvas.height = viewport.height;
            canvas.width = viewport.width;
            await page.render({
                canvasContext: context,
                viewport: viewport,
            }).promise;
            this.state.form.slideImage = canvas.toDataURL();
            this.state.preview.show = true;
        }

        if (!preventOnchange) {
            const input = file.name;
            const inputVal = input.substr(0, input.lastIndexOf(".")) || input;
            if (this.state.form.slideName === "") {
                this.state.form.slideName = inputVal;
            }
        }
    }

    async onChangeUrl(url) {
        this._alertRemove();
        this.isValidUrl = false;
        this.canSubmitForm = false;
        this.state.form.isLoading = true;
        this.state.form.url = url;
        const data = await rpc("/slides/prepare_preview/", {
            url: this.state.form.url,
            slide_category: this.props.slideCategory,
            channel_id: this.props.channelId,
        });
        this.canSubmitForm = true;
        if (data.error) {
            this._alertDisplay(data.error);
            this.state.preview.show = false;
        } else {
            if (data.info) {
                this._alertDisplay(data.info, "alert-info");
            } else {
                this._alertRemove();
            }

            this.isValidUrl = true;

            if (data.name) {
                this.state.form.slideName = data.name;
                this.state.preview.videoTitle = data.name;
                this.state.preview.hideSlideVideoTitle = false;
            } else {
                this.state.preview.hideSlideVideoTitle = true;
            }

            if (data.completion_time) {
                this.state.form.duration = Math.round(data.completion_time * 60);
            }
            if (data.image_url) {
                this.state.form.slideImage = data.image_url;
            }

            if (!data.name && !data.image_url) {
                this.state.preview.show = false;
            } else {
                this.state.preview.show = true;
            }
        }

        this.state.form.isLoading = false;
    }

    async onClickFormSubmit(forcePublished) {
        if (!this._formValidate()) {
            return;
        }
        const values = await this._formValidateGetValues(forcePublished);
        this.props.upload(values, this.props.slideCategory);
    }

    onClickSourceType(isLocalSource) {
        this.state.form.isLocalSource = isLocalSource;
    }

    /**
     * @param {string} message
     */
    _alertDisplay(message, alertClass = "alert-warning") {
        this.state.alert.message = message;
        this.state.alert.class = alertClass;
        this.state.alert.show = true;
    }

    _alertRemove() {
        this.state.alert.show = false;
        this.state.alert.message = "";
        this.state.alert.class = "";
    }

    _getSelectMenuValues() {
        const result = {};
        if (this.state.choices.tagIds.length > 0) {
            const tags = Object.fromEntries(
                this.state.choices.tags.map((tag) => [tag.value, tag.label]),
            );
            result.tag_ids = this.state.choices.tagIds.map((tagId) =>
                this._toCreate(tagId) ? [0, 0, { name: tags[tagId] }] : [4, tagId],
            );
        }
        if (!this.defaultCategoryId) {
            if (this._toCreate(this.state.choices.categoryId)) {
                const category = this.state.choices.categories.find(
                    (cat) => cat.value === this.state.choices.categoryId,
                );
                result.category_id = [0, { name: category.label }];
            } else {
                const categoryId =
                    this.state.choices.categoryId || this._getDefaultCategoryId();
                result.category_id = [categoryId];
            }
        } else {
            result.category_id = [this.defaultCategoryId];
        }
        return result;
    }

    /**
     * @returns {Number|Null}
     */
    _getDefaultCategoryId() {
        return this.state.choices.categories.length > 0
            ? this.state.choices.categories[this.state.choices.categories.length - 1]
                  .value
            : null;
    }

    async _fetch_choices(type, domain = [], fields = ["name"]) {
        const results = await rpc(`/slides/${type}/search_read`, { fields, domain });

        return results.read_results.map((choice) => ({
            value: choice.id,
            label: choice.name,
        }));
    }

    _toCreate(value) {
        return typeof value === "string" && value.startsWith("temp");
    }

    _fileReset() {
        document.getElementById("upload").value = "";
        this.file.name = false;
    }

    _formValidate() {
        this.state.form.wasValidated = true;
        return (
            document.querySelector("#o_w_slide_upload_category_form").checkValidity() &&
            this.isValidUrl
        );
    }

    /**
     * @param {boolean} forcePublished
     */
    async _formValidateGetValues(forcePublished) {
        let sourceType;
        if (this.props.slideCategory === "video") {
            sourceType = "external";
        } else {
            sourceType = this.state.form.isLocalSource ? "local_file" : "external";
        }
        const values = Object.assign(
            {
                channel_id: this.props.channelId,
                document_google_url: this.state.form.url,
                duration: this.state.form.duration,
                image_google_url: this.state.form.url,
                is_published: forcePublished,
                name: this.state.form.slideName,
                slide_category: this.props.slideCategory,
                source_type: sourceType,
                video_url: this.state.form.url,
            },
            this._getSelectMenuValues(),
        );

        if (this.file.type === "application/pdf") {
            Object.assign(values, {
                image_1920: document
                    .getElementById("data_canvas")
                    .toDataURL()
                    .split(",")[1],
                slide_category: "document",
                binary_content: this.file.data,
            });
        } else if (/^image\/.*/.test(this.file.type)) {
            Object.assign(values, {
                slide_category: "infographic",
                binary_content: this.file.data,
            });
        }
        return values;
    }
}
