frappe.provide("frappe.field_os");

frappe.field_os.Completions = class {
	constructor(app) {
		this.app = app;
		app.root.on("click", "[data-work]", (event) => this.open(event.currentTarget.dataset.work));
		app.root.on("click", "[data-start-work]", async (event) => {
			const work = await this.call("start_completion", {
				visit_id: event.currentTarget.dataset.startWork,
			});
			this.open(work.name);
		});
	}
	async call(method, args = {}) {
		return (
			await frappe.call(`erpnext.field_os.api.completions.${method}`, {
				company: this.app.company,
				...args,
			})
		).message;
	}
	can(capability) {
		return this.app.session.capabilities.includes(capability);
	}
	money(value, currency) {
		return `${currency} ${Number(value || 0).toFixed(2)}`;
	}
	async dashboard() {
		this.app.setHeading(__("Service work"));
		this.app.setLoading();
		try {
			const rows = await this.call("list_work");
			const e = frappe.utils.escape_html;
			this.app
				.content()
				.html(
					`<section class="field-os__estimates" data-work-list><div class="field-os__section-title"><h2>${__(
						"Service jobs"
					)}</h2><button class="btn btn-default btn-xs" data-work-refresh>${__(
						"Refresh"
					)}</button></div><p>${
						this.can("field_update")
							? __("Capture your assigned job's checklist, photos, signature and billables.")
							: __("Review completed service work and approve invoices.")
					}</p><div class="field-os__record-list">${
						rows
							.map(
								(row) =>
									`<button ${
										row.completion
											? `data-work="${e(row.completion)}"`
											: this.can("field_update") && !row.docstatus
											? `data-start-work="${e(row.name)}"`
											: "disabled"
									}><strong>${e(row.name)} · ${e(row.customer)}</strong><small>${e(
										row.mntc_date
									)} · ${e(row.customer_address || "")} · ${e(
										row.status
									)}</small><span>→</span></button>`
							)
							.join("") || `<p>${__("No service jobs are available.")}</p>`
					}</div></section>`
				);
			this.app
				.content()
				.find("[data-work-refresh]")
				.on("click", () => this.dashboard());
		} catch (error) {
			this.app.renderError(error.message || __("Service work could not load."));
		}
	}
	async open(name) {
		this.app.setHeading(__("Service completion"));
		try {
			const work = await this.call("get_completion", { completion_id: name });
			const e = frappe.utils.escape_html;
			const financial = work.financials;
			const buttons = [];
			if (work.status === "Draft" && this.can("field_update")) {
				buttons.push(
					`<button class="btn btn-primary btn-sm" data-work-edit>${__(
						"Capture service work"
					)}</button>`
				);
				buttons.push(
					`<button class="btn btn-default btn-sm" data-work-complete>${__(
						"Complete visit"
					)}</button>`
				);
			}
			if (work.status === "Completed" && this.can("invoice"))
				buttons.push(
					`<button class="btn btn-primary btn-sm" data-work-invoice>${__(
						"Preview invoice"
					)}</button>`
				);
			if (work.status === "Invoiced" && financial.docstatus === 1 && this.can("invoice")) {
				buttons.push(
					`<button class="btn btn-primary btn-sm" data-work-notice="Invoice">${__(
						"Preview invoice email"
					)}</button>`
				);
				if (financial.outstanding_amount > 0)
					buttons.push(
						`<button class="btn btn-default btn-sm" data-work-notice="Follow-up">${__(
							"Preview payment follow-up"
						)}</button>`
					);
			}
			this.app.content().html(
				`<section class="field-os__estimates" data-work-detail><button class="btn btn-link" data-work-back>← ${__(
					"Service jobs"
				)}</button><div class="field-os__section-title"><h2>${e(work.name)}</h2><span>${e(
					work.status
				)}</span></div><p>${e(work.customer)} · ${e(work.site || "")} · ${e(
					work.visit
				)}</p><div class="field-os__actions">${buttons.join(
					" "
				)} <button class="btn btn-default btn-sm" data-work-reload>${__(
					"Refresh"
				)}</button></div><h3>${__("Work performed")}</h3><p>${e(
					work.summary || __("No service evidence recorded yet.")
				)}</p><ul>${Object.entries(work.required_checks)
					.map(([key, label]) => `<li>${work.checklist[key] ? "✓" : "○"} ${e(label)}</li>`)
					.join("")}</ul><h3>${__("Billables")}</h3>${this.lines(
					work.billables,
					work.currency
				)}<h3>${__("Service evidence")}</h3><div class="field-os__photos">${work.photos
					.map(
						(url) =>
							`<a href="${e(url)}" target="_blank" rel="noopener"><img src="${e(
								url
							)}" alt="${__(
								"Service photo"
							)}" style="max-width:180px;max-height:140px;margin:8px"></a>`
					)
					.join("")}</div>${
					work.signature
						? `<p>${__("Signed by")} ${e(work.signer_name)}</p><img src="${e(
								work.signature
						  )}" alt="${__("Customer signature")}" style="max-width:300px;background:white">`
						: ""
				}${
					work.completed_by
						? `<p>${__("Completed by")} ${e(work.completed_by)} · ${e(work.completed_at)}</p>`
						: ""
				}${
					financial
						? `<h3>${__("Invoice")} ${e(financial.name)}</h3><p>${e(financial.status)} · ${__(
								"Total"
						  )} ${e(this.money(financial.grand_total, financial.currency))} · ${__(
								"Outstanding"
						  )} ${e(this.money(financial.outstanding_amount, financial.currency))} · ${__(
								"Due"
						  )} ${e(financial.due_date)}</p><p>${__("Approved by")} ${e(
								work.invoice_approved_by
						  )}</p>`
						: ""
				}<h3>${__("Delivery history")}</h3>${
					work.notices
						.map(
							(n) =>
								`<p>${e(n.kind)} → ${e(n.recipient)} · ${e(n.delivery_status)} · ${e(
									n.creation
								)}</p>`
						)
						.join("") || `<p>${__("No invoice emails sent.")}</p>`
				}</section>`
			);
			const panel = this.app.content();
			panel.find("[data-work-back]").on("click", () => this.dashboard());
			panel.find("[data-work-reload]").on("click", () => this.open(name));
			panel.find("[data-work-edit]").on("click", () => this.edit(work));
			panel.find("[data-work-complete]").on("click", () =>
				frappe.confirm(__("Complete this visit and lock its service evidence?"), async () => {
					await this.call("complete", { completion_id: name, version: work.version });
					this.open(name);
				})
			);
			panel.find("[data-work-invoice]").on("click", () => this.invoice(work));
			panel
				.find("[data-work-notice]")
				.on("click", (event) => this.notice(work, event.currentTarget.dataset.workNotice));
		} catch (error) {
			this.app.renderError(error.message || __("Service completion could not load."));
		}
	}
	lines(items, currency = "") {
		const e = frappe.utils.escape_html;
		return `<table class="table"><thead><tr><th>${__("Work or part")}</th><th>${__(
			"Quantity"
		)}</th><th>${__("Rate")}</th><th>${__("Warehouse")}</th></tr></thead><tbody>${items
			.map(
				(row) =>
					`<tr><td>${e(row.item_code)}</td><td>${e(String(row.qty))}</td><td>${e(
						this.money(row.rate, currency)
					)}</td><td>${e(row.warehouse || "—")}</td></tr>`
			)
			.join("")}</tbody></table>`;
	}
	async encode(file) {
		if (file.size > 5000000) throw new Error(__("Photos must be smaller than 5 MB."));
		return new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = () => resolve(reader.result.split(",")[1]);
			reader.onerror = reject;
			reader.readAsDataURL(file);
		});
	}
	async edit(work) {
		const options = await this.call("options", { completion_id: work.name });
		const dialog = new frappe.ui.Dialog({
			title: __("Capture service work"),
			size: "extra-large",
			fields: [
				{
					fieldname: "summary",
					fieldtype: "Small Text",
					label: __("Work performed"),
					reqd: 1,
					default: work.summary,
				},
				...Object.entries(work.required_checks).map(([fieldname, label]) => ({
					fieldname,
					label: __(label),
					fieldtype: "Check",
					default: work.checklist[fieldname] ? 1 : 0,
				})),
				{
					fieldname: "billables",
					fieldtype: "Table",
					label: __("Billable work and parts"),
					reqd: 1,
					in_place_edit: true,
					data: work.billables.length
						? work.billables
						: [
								{
									item_code: options.items[0]?.name,
									qty: 1,
									rate: options.items[0]?.standard_rate || 0,
									warehouse: "",
								},
						  ],
					fields: [
						{
							fieldname: "item_code",
							fieldtype: "Select",
							label: __("Item"),
							options: options.items.map((x) => x.name),
							in_list_view: 1,
							reqd: 1,
							columns: 4,
						},
						{
							fieldname: "qty",
							fieldtype: "Float",
							label: __("Quantity"),
							in_list_view: 1,
							reqd: 1,
							columns: 2,
						},
						{
							fieldname: "rate",
							fieldtype: "Float",
							precision: 2,
							label: `${__("Rate")} (${options.currency})`,
							in_list_view: 1,
							columns: 2,
						},
						{
							fieldname: "warehouse",
							fieldtype: "Select",
							label: __("Warehouse"),
							options: ["", ...options.warehouses],
							in_list_view: 1,
							columns: 2,
						},
					],
				},
				{
					fieldname: "photos",
					fieldtype: "HTML",
					options: `<label>${__(
						"Add service photos"
					)} <input data-work-photos type="file" accept="image/jpeg,image/png,image/webp" multiple></label><p>${__(
						"At least one photo is required."
					)} ${work.photos.length} ${__("already saved")}</p>`,
				},
				{
					fieldname: "signer_name",
					fieldtype: "Data",
					label: __("Customer signer"),
					reqd: 1,
					default: work.signer_name,
				},
				{
					fieldname: "signature",
					fieldtype: "Signature",
					label: __("Customer signature"),
					description: work.signature
						? __("A signature is saved. Draw here only to replace it.")
						: __("Ask the customer to sign here."),
				},
			],
			primary_action_label: __("Save service work"),
			primary_action: async (values) => {
				dialog.disable_primary_action();
				try {
					const photos = [...work.photos];
					for (const file of dialog.$wrapper.find("[data-work-photos]")[0].files)
						photos.push(
							(
								await this.call("upload_evidence", {
									completion_id: work.name,
									content: await this.encode(file),
									kind: "Photo",
								})
							).file_url
						);
					let signature = work.signature || "";
					if (values.signature?.startsWith("data:image/"))
						signature = (
							await this.call("upload_evidence", {
								completion_id: work.name,
								content: values.signature.split(",")[1],
								kind: "Signature",
							})
						).file_url;
					await this.call("save_completion", {
						completion_id: work.name,
						version: work.version,
						values: {
							summary: values.summary,
							signer_name: values.signer_name,
							signature,
							photos,
							checklist: Object.fromEntries(
								Object.keys(work.required_checks).map((key) => [key, Boolean(values[key])])
							),
							billables: values.billables.map((row) => ({
								item_code: row.item_code,
								qty: row.qty,
								rate: row.rate,
								warehouse: row.warehouse || null,
							})),
						},
					});
					dialog.hide();
					this.open(work.name);
				} finally {
					dialog.enable_primary_action();
				}
			},
		});
		dialog.show();
	}
	async invoice(work) {
		const options = await this.call("options", { completion_id: work.name });
		const dialog = new frappe.ui.Dialog({
			title: __("Prepare invoice"),
			fields: [
				{
					fieldname: "due_date",
					fieldtype: "Date",
					label: __("Payment due"),
					reqd: 1,
					default: frappe.datetime.add_days(frappe.datetime.get_today(), 30),
				},
				{
					fieldname: "tax_template",
					fieldtype: "Select",
					label: __("Sales tax template"),
					options: ["", ...options.tax_templates],
				},
			],
			primary_action_label: __("Preview invoice"),
			primary_action: async (values) => {
				const preview = await this.call("preview_invoice", { completion_id: work.name, ...values });
				dialog.hide();
				const e = frappe.utils.escape_html;
				this.approval(
					__("Approve invoice"),
					`${this.lines(preview.items, preview.currency)}<p>${__("Taxes")}: ${e(
						this.money(preview.taxes, preview.currency)
					)}<br>${__("Before rounding")}: ${e(
						this.money(preview.before_rounding, preview.currency)
					)}<br>${__("Rounding")}: ${e(this.money(preview.rounding, preview.currency))}</p><h3>${__(
						"Total"
					)}: ${e(this.money(preview.total, preview.currency))}</h3><p>${__("Due")}: ${e(
						preview.due_date
					)}</p><p>${__(
						"Approval posts the invoice to accounting and issues its stocked parts from their warehouses."
					)}</p>`,
					"approve_invoice",
					preview.proposal.id,
					work.name,
					__("Approve and post invoice")
				);
			},
		});
		dialog.show();
	}
	async notice(work, kind) {
		const options = await this.call("options", { completion_id: work.name });
		if (!options.recipients.length || !options.integrations.length) {
			frappe.msgprint(__("Add a customer email and enable an outgoing email integration first."));
			return;
		}
		const dialog = new frappe.ui.Dialog({
			title: __("Prepare invoice email"),
			fields: [
				{
					fieldname: "recipient",
					fieldtype: "Select",
					label: __("Customer email"),
					options: options.recipients,
					default: options.recipients[0],
					reqd: 1,
				},
				{
					fieldname: "integration_id",
					fieldtype: "Select",
					label: __("Sending mailbox"),
					options: options.integrations.map((x) => ({ label: x.from_address, value: x.name })),
					default: options.integrations[0].name,
					reqd: 1,
				},
			],
			primary_action_label: __("Preview email"),
			primary_action: async (values) => {
				const preview = await this.call("preview_notice", {
					completion_id: work.name,
					kind,
					...values,
				});
				dialog.hide();
				const e = frappe.utils.escape_html;
				this.approval(
					__("Approve customer email"),
					`<h3>${e(kind)} ${e(preview.invoice)}</h3><p>${__("To")}: ${e(
						preview.recipient
					)}</p><p>${__("Total")}: ${e(this.money(preview.total, preview.currency))}</p><p>${__(
						"Outstanding"
					)}: ${e(this.money(preview.outstanding, preview.currency))}</p><p>${__("Due")}: ${e(
						preview.due_date
					)}</p><p>${__(
						"The email includes the invoice's work, parts, taxes and payment balance."
					)}</p>`,
					"approve_notice",
					preview.proposal.id,
					work.name,
					__("Approve and send email")
				);
			},
		});
		dialog.show();
	}
	approval(title, html, method, proposal, name, label) {
		const key = crypto.randomUUID();
		const dialog = new frappe.ui.Dialog({
			title,
			size: "large",
			fields: [{ fieldname: "preview", fieldtype: "HTML", options: html }],
			primary_action_label: label,
			primary_action: async () => {
				dialog.disable_primary_action();
				try {
					await this.call(method, { proposal_id: proposal, idempotency_key: key });
					dialog.hide();
					this.open(name);
				} finally {
					dialog.enable_primary_action();
				}
			},
		});
		dialog.show();
	}
};
