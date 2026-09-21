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
		} catch (error) {
			app.renderError(__("Plan details could not be loaded."));
		}
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
};
