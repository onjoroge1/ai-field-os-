frappe.provide("frappe.field_os");

frappe.field_os.Demo = class {
	constructor(app) {
		this.app = app;
	}
	async call(method, args = {}) {
		return (
			await frappe.call(`erpnext.field_os.api.demo.${method}`, { company: this.app.company, ...args })
		).message;
	}
	async use(company) {
		await this.call("use_company", { company });
		this.app.company = company;
		await this.app.refresh();
		this.app.activeView = "demo";
		this.app.renderNav();
		await this.open();
	}
	async open() {
		this.app.setHeading(__("Demo guide"));
		this.app.setLoading();
		try {
			const data = await this.call("get_demo");
			const e = frappe.utils.escape_html;
			if (!data.demo) {
				this.app
					.content()
					.html(
						`<section class="field-os__estimates" data-demo-home><h2>${__(
							"Practice with a synthetic HVAC company"
						)}</h2><p>${__(
							"Create an isolated company with three customers and sites, equipment history, an urgent Inbox request, an assigned service visit, a maintenance agreement and a sample approved estimate."
						)}</p><p>${__(
							"Demo email and SMS delivery is blocked. Financial actions stay inside the demo company."
						)}</p>${
							data.system_manager
								? `<button class="btn btn-primary" data-demo-create>${__(
										"Create demo company"
								  )}</button>`
								: `<p>${__("Ask a system administrator to create a demo company.")}</p>`
						}</section>`
					);
				this.app
					.content()
					.find("[data-demo-create]")
					.on("click", () => this.create());
				return;
			}
			const m = data.manifest;
			this.app.content().html(`<section class="field-os__estimates" data-demo-guide>
			<div class="field-os__section-title"><h2>${e(data.label)}</h2><strong data-demo-generation>${__(
				"Generation"
			)} ${data.generation} · ${e(data.status)}</strong></div>
			<p>${e(data.company)}</p><p>${__(
				"All people, messages and approvals below are synthetic. External email and SMS are disabled."
			)}</p>
			${
				data.replacement
					? `<p>${__(
							"This generation is archived. Its records are retained for review."
					  )}</p><button class="btn btn-primary" data-demo-replacement>${__(
							"Open current generation"
					  )}</button>`
					: ""
			}
			<h3>${__("1. Urgent no-cooling request")}</h3><ol><li>${__(
				"Open the cafe's request, check its urgency and review the linked customer history."
			)}</li><li>${__(
				"Open Dispatch and review the planned diagnostic visit. Reassign or reschedule it within business hours."
			)}</li></ol>
			<p><button class="btn btn-default" data-demo-action="inbox">${__(
				"Open urgent Inbox request"
			)}</button> <button class="btn btn-default" data-demo-action="customer">${__(
				"Open cafe equipment history"
			)}</button> <button class="btn btn-default" data-demo-action="dispatch">${__(
				"Open Dispatch"
			)}</button></p>
			<h3>${__("2. Preventive maintenance renewal")}</h3><ol><li>${__(
				"Review the clinic's overdue visits and approaching renewal."
			)}</li><li>${__(
				"Schedule an unfulfilled visit, then create and review a renewal draft."
			)}</li></ol><button class="btn btn-default" data-demo-action="agreement">${__(
				"Open clinic agreement"
			)}</button>
			<h3>${__("3. Estimate through invoice")}</h3><ol><li>${__(
				"Review the sample estimate and its explicitly synthetic customer approval."
			)}</li><li>${__(
				"Sign in as the demo technician to capture the cafe visit's checklist, photos, customer signature and billables, then complete the visit."
			)}</li><li>${__(
				"Sign back in as the demo owner, review the invoice proposal and explicitly approve posting. Emails remain blocked in this sandbox."
			)}</li></ol><p><button class="btn btn-default" data-demo-action="estimate">${__(
				"Open approved demo estimate"
			)}</button> <button class="btn btn-default" data-demo-action="work">${__(
				"Open service work"
			)}</button></p>
			<h3>${__("Demo logins")}</h3><p>${__(
				"Use the password chosen when this generation was created. Share it only with your demo participants."
			)}</p><ul>${m.users.map((u) => `<li>${e(u.role)}: <code>${e(u.email)}</code></li>`).join("")}</ul>
			${
				data.system_manager && data.status === "Ready"
					? `<h3>${__("Start over")}</h3><p>${__(
							"Reset creates a fresh demo generation and disables the old demo logins. This company's existing work and posted invoices are retained in the archive."
					  )}</p><button class="btn btn-default" data-demo-reset>${__(
							"Preview demo reset"
					  )}</button>`
					: ""
			}</section>`);
			const panel = this.app.content();
			panel.find("[data-demo-replacement]").on("click", () => this.use(data.replacement));
			panel.find("[data-demo-action]").on("click", (event) => {
				const action = event.currentTarget.dataset.demoAction;
				if (action === "inbox") {
					this.app.renderInbox(m.thread);
				}
				if (action === "customer") this.app.loadCustomer(m.customers.cafe);
				if (action === "dispatch") this.app.renderDispatch();
				if (action === "agreement") this.app.agreements.open(m.agreement);
				if (action === "estimate") this.app.estimates.open(m.estimate);
				if (action === "work") this.app.completions.dashboard();
			});
			panel.find("[data-demo-reset]").on("click", () => this.reset());
		} catch (error) {
			this.app.renderError(error.message || __("Demo could not load."));
		}
	}
	create() {
		const key = crypto.randomUUID();
		const dialog = new frappe.ui.Dialog({
			title: __("Create demo company"),
			fields: [
				{
					fieldname: "label",
					fieldtype: "Data",
					label: __("Demo company name"),
					default: "Northstar HVAC",
					reqd: 1,
				},
				{
					fieldname: "password",
					fieldtype: "Password",
					label: __("Demo login password"),
					description: __(
						"At least twelve characters. Save this password to use the demo owner and technician accounts."
					),
					reqd: 1,
				},
			],
			primary_action_label: __("Create and open demo"),
			primary_action: async (values) => {
				dialog.disable_primary_action();
				try {
					const result = await this.call("create", { ...values, idempotency_key: key });
					dialog.hide();
					await this.use(result.company);
				} finally {
					dialog.enable_primary_action();
				}
			},
		});
		dialog.show();
	}
	async reset() {
		const preview = await this.call("preview_reset");
		const key = crypto.randomUUID();
		const dialog = new frappe.ui.Dialog({
			title: __("Approve demo reset"),
			fields: [
				{
					fieldname: "effect",
					fieldtype: "HTML",
					options: `<p>${frappe.utils.escape_html(preview.effect)}</p>`,
				},
				{
					fieldname: "password",
					fieldtype: "Password",
					label: __("New generation login password"),
					description: __("At least twelve characters."),
					reqd: 1,
				},
			],
			primary_action_label: __("Approve reset and open fresh demo"),
			primary_action: async (values) => {
				dialog.disable_primary_action();
				try {
					const result = await this.call("approve_reset", {
						...values,
						proposal_id: preview.proposal.id,
						idempotency_key: key,
					});
					dialog.hide();
					await this.use(result.company);
				} finally {
					dialog.enable_primary_action();
				}
			},
		});
		dialog.show();
	}
};
