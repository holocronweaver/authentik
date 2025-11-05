import { DEFAULT_CONFIG } from "#common/api/config";
import { MessageLevel } from "#common/messages";
import { Form } from "#elements/forms/Form";
import { showMessage } from "#elements/messages/MessageContainer";

import { FilesApi, UsageEnum } from "@goauthentik/api";

import { msg } from "@lit/localize";
import { customElement, property, state } from "lit/decorators.js";
import { html } from "lit";

@customElement("ak-file-upload-form")
export class FileUploadForm extends Form<Record<string, unknown>> {
    @property({ type: String })
    usage: UsageEnum = UsageEnum.Media;

    @state()
    selectedFile?: File;

    async send(): Promise<void> {
        if (!this.selectedFile) {
            throw new Error(msg("Please select a file"));
        }

        const api = new FilesApi(DEFAULT_CONFIG);
        const customName = (
            this.shadowRoot?.querySelector<HTMLInputElement>("#file-name")
        )?.value?.trim();

        // If custom name provided, append original extension
        let finalPath = this.selectedFile.name;
        if (customName) {
            const ext = this.selectedFile.name.substring(this.selectedFile.name.lastIndexOf('.'));
            finalPath = customName + ext;
        }

        await api.filesUploadCreate({
            file: this.selectedFile,
            path: finalPath,
            usage: this.usage,
        } as any);

        showMessage({
            level: MessageLevel.success,
            message: msg("File uploaded successfully"),
        });
    }

    renderForm() {
        return html`
            <form class="pf-c-form pf-m-horizontal">
                <div class="pf-c-form__group">
                    <label class="pf-c-form__label" for="file-input">
                        <span class="pf-c-form__label-text">${msg("File")}</span>
                        <span class="pf-c-form__label-required" aria-hidden="true">*</span>
                    </label>
                    <input
                        type="file"
                        class="pf-c-form-control"
                        id="file-input"
                        name="file"
                        required
                        @change=${(e: Event) => {
                            const input = e.target as HTMLInputElement;
                            if (input.files && input.files.length > 0) {
                                this.selectedFile = input.files[0];
                            }
                        }}
                    />
                </div>
                <div class="pf-c-form__group">
                    <label class="pf-c-form__label" for="file-name">
                        <span class="pf-c-form__label-text">${msg("File Name")}</span>
                    </label>
                    <div class="pf-c-form__group-control">
                        <input
                            type="text"
                            class="pf-c-form-control"
                            id="file-name"
                            placeholder=${msg("Leave empty to use original filename")}
                        />
                        <p class="pf-c-form__helper-text">
                            ${msg("Optionally rename the file (without extension). Leave empty to keep the original filename.")}
                        </p>
                    </div>
                </div>
            </form>
        `;
    }
}

declare global {
    interface HTMLElementTagNameMap {
        "ak-file-upload-form": FileUploadForm;
    }
}
