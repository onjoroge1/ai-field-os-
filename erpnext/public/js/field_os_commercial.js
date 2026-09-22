frappe.provide("frappe.field_os");

frappe.field_os.Commercial = class {
	constructor(app) {
		this.app = app;
	}

	async open() {
		const app = this.app;
		app.root.find('[data-role="heading"]').text(__("Plan & usage"));
		try {
			const { message: data } = await frappe.call({
				method: "erpnext.field_os.api.commercial.get_plan",
				args: { company: app.company },
			});
			if (app.activeView !== "commercial") return;
			const escape = frappe.utils.escape_html;
			app.root.find('[data-role="content"]').html(`
				<section class="field-os__panel" data-plan-summary>
					<h2>${escape(data.plan)} · ${escape(data.status)}</h2>
					<p>${__("Usage period")}: ${escape(data.period)}</p>
					${data.trial_end ? `<p>${__("Trial ends")}: ${escape(String(data.trial_end))}</p>` : ""}
					<table class="table"><thead><tr><th>${__("Resource")}</th><th>${__("Used")}</th><th>${__(
				"Allowance"
			)}</th></tr></thead><tbody>
					${["seats", "ai", "email", "sms"]
						.map(
							(key) =>
								`<tr><td>${escape(key)}</td><td>${
									key === "seats" ? data.seats : data.usage[key] || 0
								}</td><td>${data.limits[key]}</td></tr>`
						)
						.join("")}
					</tbody></table>
					<p>${__(
						"AI counts completed requests. Email and SMS count accepted outbound messages; delivery is tracked separately."
					)}</p>
					<p>${__("Enabled features")}: ${escape(data.features.join(", "))}</p>
					<div data-billing-actions></div>
				</section>`);
			await this.billing();
			await this.support();
			await this.jobs();
		} catch (error) {
			app.renderError(__("Plan details could not be loaded."));
		}
	}

	async jobs() {
		const { message: jobs } = await frappe.call({
			method: "erpnext.field_os.api.jobs.get_jobs",
			args: { company: this.app.company },
		});
		if (this.app.activeView !== "commercial") return;
		const escape = frappe.utils.escape_html;
		const panel = $(`<section class="field-os__panel" data-job-summary><h3>${__("Background jobs")}</h3>
		<p>${__(
			"Unknown delivery outcomes need a provider receipt or confirmation that nothing was sent before retrying."
		)}</p>
		<table class="table"><thead><tr><th>${__("Job")}</th><th>${__("Status")}</th><th>${__(
			"Attempts"
		)}</th><th></th></tr></thead><tbody>${jobs
			.map(
				(job) =>
					`<tr><td>${escape(job.kind)}<br><small>${escape(job.name)}</small></td><td>${escape(
						job.status
					)} ${escape(job.error_code || "")}</td><td>${job.attempts}</td><td>${
						["Dead", "Uncertain"].includes(job.status)
							? `<button class="btn btn-default btn-sm" data-replay="${escape(
									job.name
							  )}" data-state="${escape(job.status)}">${__("Review")}</button>`
							: ""
					}</td></tr>`
			)
			.join("")}</tbody></table></section>`);
		this.app.root.find('[data-role="content"]').append(panel);
		panel.find("[data-replay]").on("click", (event) => {
			const button = event.currentTarget;
			frappe.prompt(
				[
					{
						fieldname: "reason",
						fieldtype: "Small Text",
						label: __("Reason and provider evidence"),
						reqd: 1,
					},
					{
						fieldname: "resolution",
						fieldtype: "Select",
						label: __("Verified outcome"),
						options:
							button.dataset.state === "Uncertain"
								? "\nconfirmed_not_sent\nconfirmed_sent"
								: "retry",
						reqd: 1,
					},
					{
						fieldname: "external_id",
						fieldtype: "Data",
						label: __("Provider receipt (required if sent)"),
					},
				],
				async (values) => {
					await frappe.call({
						method: "erpnext.field_os.api.jobs.replay",
						args: { company: this.app.company, name: button.dataset.replay, ...values },
					});
					await this.open();
				},
				__("Reconcile job"),
				__("Record decision")
			);
		});
	}

	async billing() {
		const { message: data } = await frappe.call({
			method: "erpnext.field_os.api.billing.status",
			args: { company: this.app.company },
		});
		if (this.app.activeView !== "commercial") return;
		const area = this.app.root.find("[data-billing-actions]");
		const escape = frappe.utils.escape_html;
		area.html(`<h3>${__("Subscription billing")}</h3>
			${
				data.configured
					? `<button class="btn btn-primary" data-checkout="standard">${__(
							"Choose Standard"
					  )}</button> <button class="btn btn-default" data-checkout="pro">${__(
							"Choose Pro"
					  )}</button> ${
							data.has_customer
								? `<button class="btn btn-default" data-portal>${__(
										"Manage billing"
								  )}</button> <button class="btn btn-default" data-refresh-billing>${__(
										"Refresh payment status"
								  )}</button>`
								: ""
					  }`
					: `<p>${__(
							"Subscription checkout is not yet available. Your administrator can enable billing."
					  )}</p>`
			}
			<p>${__("Checkout shows the price and asks you to confirm before starting a subscription.")}</p>
			<table class="table"><thead><tr><th>${__("Invoice")}</th><th>${__(
			"Payment status"
		)}</th><th></th></tr></thead><tbody>${data.invoices
			.map(
				(invoice) =>
					`<tr><td>${escape(invoice.provider_id)}</td><td>${escape(invoice.status)}</td><td>${
						invoice.hosted_url
							? `<a href="${escape(
									invoice.hosted_url
							  )}" target="_blank" rel="noopener noreferrer">${__("View invoice")}</a>`
							: ""
					}</td></tr>`
			)
			.join("")}</tbody></table>`);
		area.find("[data-checkout]").on("click", (event) => {
			const plan = event.currentTarget.dataset.checkout;
			frappe.confirm(__("Continue to Stripe to review this plan and confirm your subscription?"), () =>
				this.redirect("checkout", { plan })
			);
		});
		area.find("[data-portal]").on("click", () => this.redirect("portal"));
		area.find("[data-refresh-billing]").on("click", async () => {
			await frappe.call({
				method: "erpnext.field_os.api.billing.refresh",
				args: { company: this.app.company },
			});
			await this.open();
		});
	}

	async redirect(method, args = {}) {
		const { message: data } = await frappe.call({
			method: `erpnext.field_os.api.billing.${method}`,
			args: { company: this.app.company, ...args },
		});
		window.location.assign(data.url);
	}

	async support() {
		const call = async (method, args = {}) =>
			(
				await frappe.call({
					method: `erpnext.field_os.api.support.${method}`,
					args: { company: this.app.company, ...args },
				})
			).message;
		const rows = await call("grants");
		if (this.app.activeView !== "commercial") return;
		const e = frappe.utils.escape_html;
		const area = $(`<section data-owner-support><h3>${__("Support access")}</h3><p>${__(
			"Grant up to one hour of read-only diagnostics. Revoke access at any time. This does not allow support to act as you."
		)}</p><button class="btn btn-default" data-new-grant>${__("Grant support access")}</button>
			${rows
				.map(
					(row) =>
						`<p>${e(row.support_user)} · ${e(String(row.expires_at))} · ${
							row.revoked
								? __("Revoked")
								: `<button class="btn btn-xs btn-default" data-revoke="${e(row.name)}">${__(
										"Revoke"
								  )}</button>`
						}</p>`
				)
				.join("")}</section>`);
		this.app.root.find("[data-plan-summary]").append(area);
		area.find("[data-new-grant]").on("click", () =>
			frappe.prompt(
				[
					{
						fieldname: "support_user",
						fieldtype: "Data",
						label: __("Support account email"),
						reqd: 1,
					},
					{
						fieldname: "reason",
						fieldtype: "Small Text",
						label: __("Support request (no credentials)"),
						reqd: 1,
					},
					{
						fieldname: "minutes",
						fieldtype: "Int",
						label: __("Minutes of access (5–60)"),
						default: 30,
						reqd: 1,
					},
				],
				async (values) => {
					await call("grant", values);
					await this.open();
				},
				__("Approve temporary support access"),
				__("Grant read access")
			)
		);
		area.find("[data-revoke]").on("click", async (event) => {
			await call("revoke", { grant_id: event.currentTarget.dataset.revoke });
			await this.open();
		});
	}
};
