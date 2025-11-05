import "#elements/forms/SearchSelect/index";

import { DEFAULT_CONFIG } from "#common/api/config";

import { AKElement } from "#elements/Base";
import { AKLabel } from "#components/ak-label";
import { IDGenerator } from "#packages/core/id";

import { FilesApi, UsageEnum } from "@goauthentik/api";

import { html, nothing } from "lit";
import { customElement, property } from "lit/decorators.js";

interface FileItem {
    name: string;
    url: string;
    mime_type: string;
    size: number;
    usage: string;
}

const renderElement = (item: FileItem) => item.name;
const renderValue = (item: FileItem | undefined) => item?.name;

/**
 * File Search Input Component
 *
 * Search/select dropdown for files from authentik.files storage.
 * Allows selecting uploaded files or typing Font Awesome icons (fa://...) and URLs.
 */
@customElement("ak-file-search-input")
export class AkFileSearchInput extends AKElement {
    // Render into the lightDOM
    protected createRenderRoot() {
        return this;
    }

    @property({ type: String })
    name!: string;

    @property({ type: String })
    label: string | null = null;

    @property({ type: String })
    value?: string;

    @property({ type: Boolean })
    required = false;

    @property({ type: Boolean })
    blankable = false;

    @property({ type: String })
    help: string | null = null;

    @property({ type: String })
    usage: UsageEnum = UsageEnum.Media;

    @property({ type: Boolean })
    allowFontAwesome = false;

    @property({ type: String, reflect: false })
    public fieldID?: string = IDGenerator.elementID().toString();

    #selected = (item: FileItem) => {
        return this.value === item.name;
    };

    async #fetch(query?: string): Promise<FileItem[]> {
        // Allow typing Font Awesome icons directly
        if (query && this.allowFontAwesome && query.startsWith("fa://")) {
            return [];
        }

        const api = new FilesApi(DEFAULT_CONFIG);
        const response: any = await api.filesList({
            usage: this.usage as any,
            ...(query ? { search: query } : {}),
        });

        return response.results || [];
    }

    render() {
        return html` <ak-form-element-horizontal name=${this.name}>
            <div slot="label" class="pf-c-form__group-label">
                ${AKLabel({ htmlFor: this.fieldID, required: this.required }, this.label)}
            </div>

            <ak-search-select
                style="width: 100%;"
                .fieldID=${this.fieldID}
                .fetchObjects=${this.#fetch.bind(this)}
                .renderElement=${renderElement}
                .value=${renderValue}
                .selected=${this.#selected}
                ?blankable=${this.blankable}
            >
            </ak-search-select>
            ${this.help ? html`<p class="pf-c-form__helper-text">${this.help}</p>` : nothing}
        </ak-form-element-horizontal>`;
    }
}

declare global {
    interface HTMLElementTagNameMap {
        "ak-file-search-input": AkFileSearchInput;
    }
}
