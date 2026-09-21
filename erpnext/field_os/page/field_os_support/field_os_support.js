frappe.pages["field-os-support"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Field OS Support"),
		single_column: true,
	});
	const e = frappe.utils.escape_html;
	const call = async (method, args = {}) =>
		(await frappe.call({ method: `erpnext.field_os.api.support.${method}`, args })).message;
	page.main.html(`<section class="p-4"><h2>${__("Tenant diagnostics")}</h2><p>${__(
		"Read access requires an active owner grant. Every inspection is recorded. Customer messages, credentials and private files are excluded."
	)}</p>
		<label>${__(
			"Find company"
		)}<input class="form-control" data-query></label> <button class="btn btn-default" data-search>${__(
		"Search"
	)}</button><div data-companies></div>
		<h3>${__("Your active grants")}</h3><div data-grants></div><div data-inspection></div></section>`);
	const inspect = (company, grant_id) =>
		frappe.prompt(
			[
				{
					fieldname: "reason",
					fieldtype: "Small Text",
					label: __("Reason for inspection (no credentials)"),
					reqd: 1,
				},
			],
			async ({ reason }) => {
				const data = await call("inspect", { company, grant_id, reason });
				const area = page.main.find("[data-inspection]");
				area.html(`<h3>${e(data.company)}</h3><p>${e(data.subscription.plan)} · ${e(
					data.subscription.status
				)}</p>
			<table class="table"><thead><tr><th>${__("Integration")}</th><th>${__("Enabled")}</th><th>${__(
					"Needs attention"
				)}</th></tr></thead><tbody>${data.integrations
					.map(
						(row) =>
							`<tr><td>${e(row.channel)} · ${e(row.id)}</td><td>${
								row.enabled ? __("Yes") : __("No")
							}</td><td>${row.has_error ? __("Yes") : __("No")}</td></tr>`
					)
					.join("")}</tbody></table>
			<h4>${__("Recent audit events")}</h4><table class="table"><tbody>${data.audit
					.map(
						(row) =>
							`<tr><td>${e(String(row.creation))}</td><td>${e(row.actor)}</td><td>${e(
								row.action
							)}</td><td>${e(row.outcome)}</td></tr>`
					)
					.join("")}</tbody></table><div data-flags></div>`);
				if (frappe.user_roles.includes("System Manager")) {
					area.find("[data-flags]")
						.html(
							`<button class="btn btn-default" data-configure>${__(
								"Feature availability"
							)}</button>`
						)
						.find("button")
						.on("click", () => {
							const features = ["ai", "email", "sms", "agreements", "imports"];
							frappe.prompt(
								[
									...features.map((feature) => ({
										fieldname: feature,
										fieldtype: "Check",
										label: `${__("Disable")} ${feature}`,
										default: data.subscription.disabled_features.includes(feature),
									})),
									{
										fieldname: "reason",
										fieldtype: "Small Text",
										label: __("Reason for change"),
										reqd: 1,
									},
								],
								async (values) => {
									await call("set_flags", {
										company,
										version: data.version,
										disabled: features.filter((feature) => values[feature]),
										reason: values.reason,
									});
									frappe.msgprint(
										__(
											"Feature availability updated. Reopen diagnostics to view the new version."
										)
									);
								},
								__("Change company feature availability"),
								__("Apply changes")
							);
						});
				}
			},
			__("Open read-only diagnostics"),
			__("Inspect")
		);
	page.main.find("[data-search]").on("click", async () => {
		const rows = await call("lookup", { query: page.main.find("[data-query]").val() });
		const area = page.main.find("[data-companies]");
		area.html(
			rows
				.map(
					(row) =>
						`<p>${e(row.company)} · ${e(row.plan)} · ${e(row.status)} ${
							frappe.user_roles.includes("System Manager")
								? `<button class="btn btn-xs btn-default" data-company="${e(
										row.company
								  )}">${__("Inspect")}</button>`
								: ""
						}</p>`
				)
				.join("")
		);
		area.find("[data-company]").on("click", (event) => inspect(event.currentTarget.dataset.company, ""));
	});
	call("my_grants").then((rows) => {
		const area = page.main.find("[data-grants]");
		area.html(
			rows
				.map(
					(row) =>
						`<p>${e(row.company)} · ${e(
							String(row.expires_at)
						)} <button class="btn btn-xs btn-default" data-grant="${e(
							row.name
						)}" data-company="${e(row.company)}">${__("Inspect")}</button></p>`
				)
				.join("") || `<p>${__("No active owner grants")}</p>`
		);
		area.find("[data-grant]").on("click", (event) =>
			inspect(event.currentTarget.dataset.company, event.currentTarget.dataset.grant)
		);
	});
};
