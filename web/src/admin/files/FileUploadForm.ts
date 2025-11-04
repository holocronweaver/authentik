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
            throw new Error("No file selected");
        }

        const api = new FilesApi(DEFAULT_CONFIG);
        const friendlyName = (
            this.shadowRoot?.querySelector<HTMLInputElement>("#friendly-name")
        )?.value;

        await api.filesUploadCreate({
            file: this.selectedFile,
            friendlyName: friendlyName || undefined,
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
                        required
                        @change=${(e: Event) => {
                            const input = e.target as HTMLInputElement;
                            if (input.files && input.files.length > 0) {
                                this.selectedFile = input.files[0];
                                // Auto-fill friendly name if empty
                                const nameInput =
                                    this.shadowRoot?.querySelector<HTMLInputElement>(
                                        "#friendly-name",
                                    );
                                if (nameInput && !nameInput.value) {
                                    nameInput.value = this.selectedFile.name;
                                }
                            }
                        }}
                    />
                </div>
                <div class="pf-c-form__group">
                    <label class="pf-c-form__label" for="friendly-name">
                        <span class="pf-c-form__label-text">${msg("Friendly Name")}</span>
                    </label>
                    <input
                        type="text"
                        class="pf-c-form-control"
                        id="friendly-name"
                        placeholder=${msg("Leave empty to auto-generate")}
                    />
                    <p class="pf-c-form__helper-text">
                        ${msg("Display name for the file. If empty, UUID will be used.")}
                    </p>
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
