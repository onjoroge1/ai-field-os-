frappe.provide("frappe.field_os");

frappe.field_os.Migrations = class {
	constructor(app) {
		this.app = app;
	}
	async call(method, args = {}) {
		return (
			await frappe.call(`erpnext.field_os.api.migrations.${method}`, {
				company: this.app.company,
				...args,
			})
		).message;
	}
	download(name, content) {
		const url = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
		const link = document.createElement("a");
		link.href = url;
		link.download = name;
		link.click();
		setTimeout(() => URL.revokeObjectURL(url), 1000);
	}
	async open() {
		this.app.setHeading(__("Data import"));
		this.app.setLoading();
		try {
			const rows = await this.call("list_batches");
			const e = frappe.utils.escape_html;
			this.app.content().html(`<section class="field-os__estimates" data-import-home>
			<h2>${__("Bring your customer history into Field OS")}</h2>
			<p>${__(
				"Import customers first, then their sites, then equipment. Use the same external IDs in each file. Imports create new records; they do not update existing customers."
			)}</p>
			<label>${__("Import type")} <select class="form-control" data-import-kind><option value="customers">${__(
				"Customers"
			)}</option><option value="sites">${__("Sites")}</option><option value="equipment">${__(
				"Equipment"
			)}</option></select></label>
			<p><button class="btn btn-default" data-import-template>${__("Download CSV template")}</button></p>
			<label>${__(
				"Choose CSV (up to 1000 rows, 2 MB)"
			)} <input type="file" accept=".csv,text/csv" data-import-file></label>
			<p><button class="btn btn-primary" data-import-validate>${__("Run dry run")}</button></p>
			<p>${__(
				"Dry runs validate your data without creating customers, sites or equipment. Sites use the company's country."
			)}</p>
			<h3>${__("Import history")}</h3><div class="field-os__record-list">${
				rows
					.map(
						(row) =>
							`<button data-import-batch="${e(row.name)}"><strong>${e(row.name)} · ${e(
								row.migration_kind
							)}</strong><small>${e(row.status)} · ${e(row.creation)} · ${e(
								row.owner
							)}</small><span>→</span></button>`
					)
					.join("") || `<p>${__("No imports yet.")}</p>`
			}</div></section>`);
			const panel = this.app.content();
			panel.find("[data-import-template]").on("click", async () => {
				const kind = panel.find("[data-import-kind]").val();
				this.download(`${kind}-template.csv`, await this.call("template", { kind }));
			});
			panel
				.find("[data-import-batch]")
				.on("click", (event) => this.batch(event.currentTarget.dataset.importBatch));
			panel.find("[data-import-validate]").on("click", async (event) => {
				const file = panel.find("[data-import-file]")[0].files[0];
				if (!file || file.size > 2000000)
					return frappe.msgprint(__("Choose a CSV file smaller than 2 MB."));
				event.currentTarget.disabled = true;
				try {
					const batch = await this.call("validate_csv", {
						kind: panel.find("[data-import-kind]").val(),
						content: await file.text(),
					});
					this.batch(batch.name);
				} finally {
					event.currentTarget.disabled = false;
				}
			});
		} catch (error) {
			this.app.renderError(error.message || __("Imports could not load."));
		}
	}
	async batch(name) {
		const batch = await this.call("get_batch", { batch_id: name });
		const e = frappe.utils.escape_html;
		const columns = Object.keys(batch.rows[0].data);
		this.app.content().html(`<section class="field-os__estimates" data-import-detail>
		<button class="btn btn-link" data-import-back>← ${__("All imports")}</button>
		<div class="field-os__section-title"><h2>${e(batch.name)}</h2><strong data-import-status>${e(
			batch.status
		)}</strong></div>
		<p>${batch.rows.length} ${e(batch.kind)} · ${__("Reviewed by")} ${e(batch.created_by)} · ${e(
			batch.creation
		)}</p>
		${batch.applied_by ? `<p>${__("Applied by")} ${e(batch.applied_by)}</p>` : ""}
		${batch.rolled_back_by ? `<p>${__("Rolled back by")} ${e(batch.rolled_back_by)}</p>` : ""}
		<div class="field-os__actions">${
			batch.status === "Validated"
				? `<button class="btn btn-primary" data-import-apply>${__("Apply import")}</button>`
				: ""
		}
		${
			batch.status === "Applied"
				? `<button class="btn btn-default" data-import-rollback>${__("Preview rollback")}</button>`
				: ""
		}
		<button class="btn btn-default" data-import-report>${__("Download error report")}</button></div>
		${batch.status === "Apply Failed" ? `<p role="alert">${e(batch.error_report)}</p>` : ""}
		<div style="overflow-x:auto"><table class="table"><thead><tr><th>${__("CSV row")}</th>${columns
			.map((c) => `<th>${e(c)}</th>`)
			.join("")}<th>${__("Validation")}</th></tr></thead><tbody data-import-rows></tbody></table></div>
		<button class="btn btn-default" data-import-more>${__("Show more rows")}</button>
		${
			batch.records.length
				? `<h3>${__("Created records")}</h3><ul>${batch.records
						.map((r) => `<li>${e(r.doctype)} · ${e(r.name)}</li>`)
						.join("")}</ul>`
				: ""
		}</section>`);
		const panel = this.app.content();
		let shown = 0;
		const more = () => {
			panel.find("[data-import-rows]").append(
				batch.rows
					.slice(shown, shown + 50)
					.map(
						(row) =>
							`<tr><td>${row.number}</td>${columns
								.map((c) => `<td>${e(row.data[c])}</td>`)
								.join("")}<td>${e(row.errors.join("; ") || __("Valid"))}</td></tr>`
					)
					.join("")
			);
			shown += 50;
			panel.find("[data-import-more]").toggle(shown < batch.rows.length);
		};
		more();
		panel.find("[data-import-more]").on("click", more);
		panel.find("[data-import-back]").on("click", () => this.open());
		panel
			.find("[data-import-report]")
			.on("click", () => this.download(`${name}-errors.csv`, batch.error_report));
		panel.find("[data-import-apply]").on("click", () =>
			frappe.confirm(
				__("Create {0} new {1} records in {2}?", [
					batch.rows.length,
					batch.kind,
					e(this.app.company),
				]),
				async () => {
					await this.call("apply", { batch_id: name, version: batch.version });
					this.batch(name);
				}
			)
		);
		panel.find("[data-import-rollback]").on("click", async () => {
			const preview = await this.call("preview_rollback", { batch_id: name });
			const key = crypto.randomUUID();
			const dialog = new frappe.ui.Dialog({
				title: __("Approve import rollback"),
				fields: [
					{
						fieldname: "review",
						fieldtype: "HTML",
						options: `<p>${__(
							"This permanently removes these imported records. Changed records and records with new dependencies are protected."
						)}</p><ul>${preview.records
							.map((r) => `<li>${e(r.doctype)} · ${e(r.name)}</li>`)
							.join("")}</ul>`,
					},
				],
				primary_action_label: __("Approve and remove imported records"),
				primary_action: async () => {
					dialog.disable_primary_action();
					try {
						await this.call("approve_rollback", {
							proposal_id: preview.proposal.id,
							idempotency_key: key,
						});
						dialog.hide();
						this.batch(name);
					} finally {
						dialog.enable_primary_action();
					}
				},
			});
			dialog.show();
		});
	}
};
