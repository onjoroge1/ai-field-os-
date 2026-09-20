frappe.provide("frappe.field_os");

frappe.field_os.Estimates = class {
	constructor(app) {
		this.app = app;
		app.root.on("click", "[data-estimate]", (event) => this.open(event.currentTarget.dataset.estimate));
		app.root.on("click", "[data-new-estimate]", (event) =>
			this.edit(event.currentTarget.dataset.newEstimate)
		);
	}

	async call(method, args = {}) {
		return (
			await frappe.call(`erpnext.field_os.api.estimates.${method}`, {
				company: this.app.company,
				...args,
			})
		).message;
	}

	async renderCustomer(customer) {
		const e = frappe.utils.escape_html;
		const panel = $(
			`<section class="field-os__estimates" data-estimate-list><div class="field-os__section-title"><h2>${__(
				"Estimates"
			)}</h2>${
				this.app.session.capabilities.includes("quote")
					? `<button class="btn btn-default btn-xs" data-new-estimate="${e(customer)}">${__(
							"New estimate"
					  )}</button>`
					: ""
			}</div><div data-estimate-rows>${__("Loading estimates…")}</div></section>`
		).appendTo(this.app.content());
		try {
			const rows = await this.call("list_estimates", { customer_id: customer });
			panel
				.find("[data-estimate-rows]")
				.html(
					rows.length
						? `<div class="field-os__record-list">${rows
								.map(
									(row) =>
										`<button data-estimate="${e(row.name)}"><strong>${e(
											row.name
										)}</strong><small>${e(row.status)} · ${e(
											row.recipient
										)}</small><span>→</span></button>`
								)
								.join("")}</div>`
						: `<p class="text-muted">${__("No estimates yet.")}</p>`
				);
		} catch (error) {
			panel.find("[data-estimate-rows]").text(error.message || __("Estimates could not load."));
		}
	}

	async open(name) {
		this.app.setLoading();
		try {
			const item = await this.call("get_estimate", { estimate_id: name });
			this.app.setHeading(__("Estimate"));
			const e = frappe.utils.escape_html;
			const money = (value) => e(`${item.currency} ${Number(value).toFixed(2)}`);
			this.app.content().html(`<section class="field-os__estimates" data-estimate-detail>
				<button class="btn btn-default btn-xs" data-customer="${e(item.customer)}">← ${__("Customer")}</button>
				<div class="field-os__section-title"><h2>${e(item.name)}</h2><strong>${e(item.status)}</strong></div>
				<p>${__("Customer")}: ${e(item.customer)} · ${__("Email")}: ${e(item.recipient)}</p>
				<p>${__("Valid until")}: ${e(item.valid_until)}${
				item.delivery_status ? ` · ${__("Email delivery")}: ${e(item.delivery_status)}` : ""
			}</p>
				<div class="table-responsive"><table class="table"><thead><tr><th>${__("Item")}</th><th>${__(
				"Quantity"
			)}</th><th>${__("Rate")}</th><th>${__("Amount")}</th><th>${__(
				"Warehouse / on hand"
			)}</th></tr></thead><tbody>${item.items
				.map(
					(row) =>
						`<tr><td>${e(row.item_code)}<br><small>${e(row.description)}</small></td><td>${e(
							String(row.qty)
						)}</td><td>${money(row.rate)}</td><td>${money(row.amount)}</td><td>${e(
							row.warehouse || "—"
						)} / ${e(row.on_hand == null ? "—" : String(row.on_hand))}</td></tr>`
				)
				.join("")}</tbody></table></div>
				<p>${__("Taxes")}: ${money(item.taxes)}</p><h3>${__("Total")}: ${money(item.total)}</h3>
				<div data-estimate-actions></div>
				${item.decisions
					.map(
						(row) =>
							`<article><h3>${e(row.decision)}</h3><p>${e(row.customer_name)} · ${e(
								row.decided_at
							)}</p><p>${e(row.comment || "")}</p><small>${e(row.evidence)}</small></article>`
					)
					.join("")}
			</section>`);
			const actions = this.app.content().find("[data-estimate-actions]");
			if (this.app.session.capabilities.includes("quote")) {
				if (item.status === "Draft") {
					$(`<button class="btn btn-default" data-estimate-edit>${__("Edit draft")}</button>`)
						.appendTo(actions)
						.on("click", () => this.edit(item.customer, item));
					$(`<button class="btn btn-primary" data-estimate-preview>${__("Preview send")}</button>`)
						.appendTo(actions)
						.on("click", () => this.preview(item.name));
				} else if (item.status === "Sent") {
					$(
						`<button class="btn btn-default" data-estimate-record-decision>${__(
							"Record customer decision"
						)}</button>`
					)
						.appendTo(actions)
						.on("click", () => this.recordDecision(item));
				} else {
					$(
						`<button class="btn btn-default" data-estimate-revise>${__(
							"Create revision"
						)}</button>`
					)
						.appendTo(actions)
						.on("click", () => this.edit(item.customer, item, true));
				}
			}
			$(`<button class="btn btn-default">${__("Refresh estimate")}</button>`)
				.appendTo(actions)
				.on("click", () => this.open(item.name));
		} catch (error) {
			this.app.renderError(error.message || __("Estimate could not load."));
		}
	}

	async edit(customer, item = null, revision = false) {
		const options = await this.call("options", { customer_id: customer });
		if (!options.recipients.length || !options.integrations.length || !options.items.length) {
			frappe.msgprint(
				__(
					"Add a customer email, an enabled company email integration with an outgoing account, and sales items before creating an estimate."
				)
			);
			return;
		}
		const dialog = new frappe.ui.Dialog({
			title: item && !revision ? __("Edit estimate") : __("New estimate"),
			size: "extra-large",
			fields: [
				{
					fieldname: "recipient",
					fieldtype: "Select",
					label: __("Customer email"),
					options: options.recipients,
					default: item?.recipient || options.recipients[0],
					reqd: 1,
				},
				{
					fieldname: "email_integration",
					fieldtype: "Select",
					label: __("Send from"),
					options: options.integrations.map((row) => ({
						value: row.name,
						label: row.from_address,
					})),
					default:
						item?.email_integration ||
						options.defaults?.email_integration ||
						options.integrations[0].name,
					reqd: 1,
				},
				{
					fieldname: "valid_until",
					fieldtype: "Date",
					label: __("Valid until"),
					default: revision
						? frappe.datetime.add_days(frappe.datetime.get_today(), 14)
						: item?.valid_until || frappe.datetime.add_days(frappe.datetime.get_today(), 14),
					reqd: 1,
				},
				{
					fieldname: "tax_template",
					fieldtype: "Select",
					label: __("Tax template"),
					options: ["", ...options.tax_templates],
					default: item?.tax_template || "",
				},
				{
					fieldname: "items",
					fieldtype: "Table",
					label: __("Labor and required parts"),
					reqd: 1,
					in_place_edit: true,
					data: item
						? item.items.map((row) => ({
								item_code: row.item_code,
								qty: row.qty,
								rate: row.rate,
								warehouse: row.warehouse,
						  }))
						: [
								{
									item_code: options.items[0].name,
									qty: 1,
									rate: options.items[0].standard_rate || 0,
									warehouse: options.warehouses[0] || "",
								},
						  ],
					fields: [
						{
							fieldname: "item_code",
							fieldtype: "Select",
							label: __("Item"),
							options: options.items.map((row) => row.name),
							reqd: 1,
							in_list_view: 1,
						},
						{
							fieldname: "qty",
							fieldtype: "Float",
							label: __("Quantity"),
							default: 1,
							reqd: 1,
							in_list_view: 1,
						},
						{
							fieldname: "rate",
							fieldtype: "Float",
							precision: 2,
							label: `${__("Rate")} (${options.currency})`,
							reqd: 1,
							in_list_view: 1,
						},
						{
							fieldname: "warehouse",
							fieldtype: "Select",
							label: __("Warehouse"),
							options: ["", ...options.warehouses],
							in_list_view: 1,
						},
					],
				},
			],
			primary_action_label: __("Save draft"),
			primary_action: async (values) => {
				dialog.disable_primary_action();
				try {
					const result = await this.call("save_estimate", {
						customer_id: customer,
						estimate_id: revision ? undefined : item?.name,
						expected_version: item?.version,
						values: {
							...values,
							revision_of: revision ? item.name : undefined,
							items: values.items.map(({ item_code, qty, rate, warehouse }) => ({
								item_code,
								qty,
								rate,
								warehouse,
							})),
						},
					});
					dialog.hide();
					await this.open(result.name);
				} finally {
					dialog.enable_primary_action();
				}
			},
		});
		dialog.show();
	}

	async preview(name) {
		const preview = await this.call("preview_send", { estimate_id: name });
		const item = preview.estimate;
		const e = frappe.utils.escape_html;
		const dialog = new frappe.ui.Dialog({
			title: __("Review estimate email"),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p>${__("Send to")}: <strong>${e(item.recipient)}</strong></p><p>${__(
						"Total including taxes"
					)}: <strong>${e(item.currency)} ${e(Number(item.total).toFixed(2))}</strong></p><p>${__(
						"The customer will receive a private link to approve or decline this quotation."
					)}</p>${
						preview.shortages.length
							? `<div class="alert alert-warning">${__(
									"Parts need replenishment. Sending does not reserve inventory."
							  )}<ul>${preview.shortages
									.map(
										(row) =>
											`<li>${e(row.item_code)}: ${e(String(row.quantity))} ${__(
												"required"
											)}, ${e(String(row.available_quantity))} ${__("on hand")}</li>`
									)
									.join("")}</ul></div>`
							: ""
					}`,
				},
			],
			primary_action_label: __("Approve and send"),
			primary_action: async () => {
				dialog.disable_primary_action();
				try {
					await this.call("approve_send", {
						proposal_id: preview.proposal.id,
						idempotency_key: preview.proposal.id,
					});
					dialog.hide();
					await this.open(name);
				} finally {
					dialog.enable_primary_action();
				}
			},
		});
		dialog.show();
	}

	recordDecision(item) {
		const dialog = new frappe.ui.Dialog({
			title: __("Record customer decision"),
			fields: [
				{
					fieldname: "decision",
					fieldtype: "Select",
					label: __("Decision"),
					options: ["Approved", "Rejected"],
					reqd: 1,
				},
				{ fieldname: "customer_name", fieldtype: "Data", label: __("Customer approver"), reqd: 1 },
				{
					fieldname: "evidence",
					fieldtype: "Small Text",
					label: __("Evidence (email reference or phone confirmation)"),
					reqd: 1,
				},
				{ fieldname: "comment", fieldtype: "Small Text", label: __("Comment") },
			],
			primary_action_label: __("Record decision"),
			primary_action: async (values) => {
				dialog.disable_primary_action();
				try {
					await this.call("record_decision", { estimate_id: item.name, ...values });
					dialog.hide();
					await this.open(item.name);
				} finally {
					dialog.enable_primary_action();
				}
			},
		});
		dialog.show();
	}
};
