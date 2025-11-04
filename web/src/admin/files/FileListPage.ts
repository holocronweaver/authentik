import "#admin/files/FileUploadForm";
import "#elements/buttons/SpinnerButton/index";
import "#elements/forms/DeleteBulkForm";
import "#elements/forms/ModalForm";
import "@patternfly/elements/pf-tooltip/pf-tooltip.js";

import { DEFAULT_CONFIG } from "#common/api/config";

import { PaginatedResponse, TableColumn } from "#elements/table/Table";
import { TablePage } from "#elements/table/TablePage";
import { SlottedTemplateResult } from "#elements/types";

import { FilesApi, UsageEnum } from "@goauthentik/api";

import { msg } from "@lit/localize";
import { html, TemplateResult } from "lit";
import { customElement, property } from "lit/decorators.js";

interface FileItem {
    uuid: string;
    friendly_name: string;
    url: string;
    mime_type: string;
    size: number;
    created_at: string;
    usage: string;
}

interface UsageType {
    value: string;
    label: string;
}

@customElement("ak-files-list")
export class FileListPage extends TablePage<FileItem> {
    checkbox = true;
    clearOnRefresh = true;

    protected override searchEnabled = true;
    public pageTitle = msg("Files");
    public pageDescription = msg("Manage uploaded files.");
    public pageIcon = "pf-icon pf-icon-folder-open";

    @property()
    order = "name";

    @property()
    usage: UsageEnum = UsageEnum.Media;

    @property({ type: Array })
    usageTypes: UsageType[] = [];

    async firstUpdated(): Promise<void> {
        super.firstUpdated();
        await this.fetchUsageTypes();
    }

    async fetchUsageTypes(): Promise<void> {
        const api = new FilesApi(DEFAULT_CONFIG);
        const response = await api.filesUsagesList();
        this.usageTypes = response as UsageType[];
    }

    async apiEndpoint(): Promise<PaginatedResponse<FileItem>> {
        const api = new FilesApi(DEFAULT_CONFIG);
        const response: any = await api.filesList({
            usage: this.usage as any,
        });

        return response as PaginatedResponse<FileItem>;
    }

    protected columns: TableColumn[] = [
        [msg("Name"), "friendly_name"],
        [msg("Type")],
        [msg("Size")],
        [msg("Created")],
        [msg("Actions"), null, msg("Row Actions")],
    ];

    renderToolbarSelected(): TemplateResult {
        const disabled = this.selectedElements.length < 1;
        return html`<ak-forms-delete-bulk
            objectLabel=${msg("File(s)")}
            .objects=${this.selectedElements}
            .metadata=${(item: FileItem) => {
                return [
                    { key: msg("Name"), value: item.friendly_name },
                    { key: msg("Type"), value: item.mime_type },
                ];
            }}
            .delete=${(item: FileItem) => {
                return new FilesApi(DEFAULT_CONFIG).filesDeleteDestroy({
                    name: item.uuid,
                    usage: item.usage as any,
                });
            }}
        >
            <button ?disabled=${disabled} slot="trigger" class="pf-c-button pf-m-danger">
                ${msg("Delete")}
            </button>
        </ak-forms-delete-bulk>`;
    }

    row(item: FileItem): SlottedTemplateResult[] {
        const formatBytes = (bytes: number) => {
            if (bytes === 0) return "0 B";
            const k = 1024;
            const sizes = ["B", "KB", "MB", "GB"];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return Math.round(bytes / Math.pow(k, i) * 100) / 100 + " " + sizes[i];
        };

        const formatDate = (dateStr: string) => {
            if (!dateStr) return "-";
            return new Date(dateStr).toLocaleString();
        };

        return [
            html`<div>${item.friendly_name}</div>`,
            html`<div>${item.mime_type || "-"}</div>`,
            html`<div>${formatBytes(item.size)}</div>`,
            html`<div>${formatDate(item.created_at)}</div>`,
            html`<div>
                <a
                    class="pf-c-button pf-m-secondary"
                    target="_blank"
                    href=${item.url}
                    rel="noopener noreferrer"
                >
                    <pf-tooltip position="top" content=${msg("Open")}>
                        <i class="fas fa-external-link-alt" aria-hidden="true"></i>
                    </pf-tooltip>
                </a>
            </div>`,
        ];
    }

    renderSectionBefore(): TemplateResult {
        return html`
            <div class="pf-c-toolbar">
                <div class="pf-c-toolbar__content">
                    <div class="pf-c-toolbar__group">
                        <div class="pf-c-toolbar__item">
                            <select
                                class="pf-c-form-control"
                                @change=${(e: Event) => {
                                    const target = e.target as HTMLSelectElement;
                                    this.usage = target.value as UsageEnum;
                                    this.fetch();
                                }}
                            >
                                ${this.usageTypes.map(
                                    (usageType) => html`
                                        <option
                                            value=${usageType.value}
                                            ?selected=${this.usage === usageType.value}
                                        >
                                            ${usageType.label}
                                        </option>
                                    `,
                                )}
                            </select>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    renderObjectCreate(): TemplateResult {
        return html`
            <ak-forms-modal>
                <span slot="submit">${msg("Upload")}</span>
                <span slot="header">${msg("Upload File")}</span>
                <ak-file-upload-form slot="form" .usage=${this.usage}> </ak-file-upload-form>
                <button slot="trigger" class="pf-c-button pf-m-primary">
                    ${msg("Upload File")}
                </button>
            </ak-forms-modal>
        `;
    }
}

declare global {
    interface HTMLElementTagNameMap {
        "ak-files-list": FileListPage;
    }
}
