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
		} catch (error) {
			app.renderError(__("Plan details could not be loaded."));
		}
	}
};
