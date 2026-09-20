frappe.provide("frappe.field_os");

frappe.field_os.Agreements = class {
	constructor(app) {
		this.app = app;
		app.root.on("click", "[data-agreement]", (event) => this.open(event.currentTarget.dataset.agreement));
		app.root.on("click", "[data-new-agreement]", (event) =>
			this.edit(event.currentTarget.dataset.newAgreement)
		);
	}
	async call(method, args = {}) {
		return (
			await frappe.call(`erpnext.field_os.api.agreements.${method}`, {
				company: this.app.company,
				...args,
			})
		).message;
	}
	canEdit() {
		return this.app.session.capabilities.includes("dispatch");
	}
	async renderCustomer(customer) {
		const e = frappe.utils.escape_html;
		const panel = $(
			`<section class="field-os__estimates" data-agreement-list><div class="field-os__section-title"><h2>${__(
				"Maintenance agreements"
			)}</h2>${
				this.canEdit()
					? `<button class="btn btn-default btn-xs" data-new-agreement="${e(customer)}">${__(
							"New agreement"
					  )}</button>`
					: ""
			}</div><div data-agreement-rows>${__("Loading…")}</div></section>`
		).appendTo(this.app.content());
		try {
			this.rows(
				panel.find("[data-agreement-rows]"),
				(await this.call("dashboard", { customer_id: customer })).agreements
			);
		} catch (error) {
			panel.find("[data-agreement-rows]").text(error.message || __("Agreements could not load."));
		}
	}
	rows(panel, items) {
		const e = frappe.utils.escape_html;
		panel.html(
			items.length
				? `<div class="field-os__record-list">${items
						.map(
							(item) =>
								`<button data-agreement="${e(item.name)}"><strong>${e(item.name)} · ${e(
									item.customer
								)}</strong><small>${e(item.effective_status)} · ${e(item.site)} · ${__(
									"Ends"
								)} ${e(item.ends_on)}</small><span>→</span></button>`
						)
						.join("")}</div>`
				: `<p>${__("No agreements yet. Create one from a customer's profile.")}</p>`
		);
	}
	async dashboard() {
		this.app.setHeading(__("Maintenance agreements"));
		this.app.setLoading();
		try {
			const data = await this.call("dashboard");
			const e = frappe.utils.escape_html;
			this.app.content().html(
				`<section class="field-os__estimates" data-agreement-dashboard><div class="field-os__section-title">${[
					["active", __("Active")],
					["due", __("Due this month")],
					["overdue", __("Overdue")],
					["renewals", __("Renewals needed")],
				]
					.map(
						([key, label]) => `<div><strong>${data.counts[key]}</strong><p>${e(label)}</p></div>`
					)
					.join("")}</div><label>${__(
					"Show"
				)} <select class="form-control" data-agreement-filter><option value="all">${__(
					"All agreements"
				)}</option><option value="overdue">${__(
					"Overdue visits"
				)}</option><option value="renewals">${__(
					"Renewals needed"
				)}</option></select></label><div data-agreement-rows></div></section>`
			);
			const render = () => {
				const filter = this.app.content().find("[data-agreement-filter]").val();
				const today = frappe.datetime.get_today();
				this.rows(
					this.app.content().find("[data-agreement-rows]"),
					data.agreements.filter(
						(item) =>
							filter === "all" ||
							(filter === "overdue"
								? !["Paused", "Cancelled"].includes(item.status) &&
								  item.visits.some((v) => v.state === "Overdue")
								: ["Active", "Paused", "Expired"].includes(item.status) &&
								  !item.renewal &&
								  frappe.datetime.get_day_diff(item.ends_on, today) <=
										item.renewal_notice_days)
					)
				);
			};
			this.app.content().find("[data-agreement-filter]").on("change", render);
			render();
		} catch (error) {
			this.app.renderError(error.message || __("Agreements could not load."));
		}
	}
	async edit(customer, item = null) {
		const options = await this.call("options", { customer_id: customer });
		if (!options.sites.length || !options.items.length) {
			frappe.msgprint(__("Add a customer site and an enabled service item first."));
			return;
		}
		const dialog = new frappe.ui.Dialog({
			title: item ? __("Edit agreement") : __("New agreement"),
			fields: [
				{
					fieldname: "site",
					fieldtype: "Select",
					label: __("Service site"),
					options: options.sites.map((s) => ({ value: s.id, label: s.title })),
					default: item?.site || options.sites[0].id,
					reqd: 1,
					read_only: Boolean(item),
				},
				{
					fieldname: "service_item",
					fieldtype: "Select",
					label: __("Service item"),
					options: options.items,
					default: item?.service_item || options.items[0],
					reqd: 1,
				},
				{
					fieldname: "starts_on",
					fieldtype: "Date",
					label: __("Starts on"),
					default: item?.starts_on || frappe.datetime.get_today(),
					reqd: 1,
				},
				{
					fieldname: "ends_on",
					fieldtype: "Date",
					label: __("Ends on"),
					default: item?.ends_on || frappe.datetime.add_months(frappe.datetime.get_today(), 12),
					reqd: 1,
				},
				{
					fieldname: "interval_months",
					fieldtype: "Int",
					label: __("Visit interval (months)"),
					default: item?.interval_months || 6,
					reqd: 1,
				},
				{
					fieldname: "renewal_notice_days",
					fieldtype: "Int",
					label: __("Renewal notice (days)"),
					default: item?.renewal_notice_days ?? 30,
					reqd: 1,
				},
			],
			primary_action_label: __("Save draft"),
			primary_action: async (values) => {
				const { site, ...terms } = values;
				const saved = await this.call("save_agreement", {
					customer_id: customer,
					site_id: site,
					values: terms,
					agreement_id: item?.name,
					modified: item?.modified,
				});
				dialog.hide();
				await this.open(saved.name);
			},
		});
		dialog.show();
	}
	async open(name) {
		this.app.setLoading();
		try {
			const item = await this.call("get_agreement", { agreement_id: name });
			const e = frappe.utils.escape_html;
			this.app.setHeading(__("Maintenance agreement"));
			this.app
				.content()
				.html(
					`<section class="field-os__estimates" data-agreement-detail><button class="btn btn-default btn-xs" data-customer="${e(
						item.customer
					)}">← ${__("Customer")}</button><div class="field-os__section-title"><h2>${e(
						item.name
					)}</h2><strong>${e(item.effective_status)}</strong></div><p>${e(item.customer)} · ${e(
						item.site
					)}</p><p>${e(item.starts_on)} → ${e(item.ends_on)} · ${__("Visit interval")}: ${
						item.interval_months
					} ${__("months")}</p><p>${e(item.service_item)}</p><div data-agreement-actions></div>${
						item.renewal
							? `<p>${__("Renewal")}: <button class="btn btn-link" data-agreement="${e(
									item.renewal
							  )}">${e(item.renewal)}</button></p>`
							: ""
					}<h3>${__("Recurring visits")}</h3><p>${__(
						"Due dates follow the contract cadence. Scheduling creates a service job in Dispatch."
					)}</p><div class="table-responsive"><table class="table"><thead><tr><th>${__(
						"Due date"
					)}</th><th>${__("Status")}</th><th>${__(
						"Service job"
					)}</th><th></th></tr></thead><tbody>${item.visits
						.map(
							(v) =>
								`<tr><td>${e(v.due_on)}</td><td>${e(v.state)}</td><td>${e(
									v.maintenance_visit || "—"
								)}${v.scheduled_for ? ` · ${e(v.scheduled_for)}` : ""}</td><td>${
									this.canEdit() &&
									(!v.maintenance_visit || v.state === "Cancelled") &&
									["Active", "Expired"].includes(item.status)
										? `<button class="btn btn-default btn-xs" data-schedule-visit="${e(
												v.name
										  )}">${__("Schedule visit")}</button>`
										: ""
								}</td></tr>`
						)
						.join("")}</tbody></table></div></section>`
				);
			const actions = this.app.content().find("[data-agreement-actions]");
			const button = (label, attr, fn) =>
				$(`<button class="btn btn-default" ${attr}>${label}</button>`)
					.appendTo(actions)
					.on("click", fn);
			if (this.canEdit()) {
				if (item.status === "Draft")
					button(__("Edit draft"), "data-edit-agreement", () => this.edit(item.customer, item));
				if (["Draft", "Paused"].includes(item.status) && item.effective_status !== "Expired")
					button(__("Activate agreement"), "data-activate-agreement", () =>
						this.status(item, "Active")
					);
				if (item.effective_status === "Active")
					button(__("Pause agreement"), "data-pause-agreement", () => this.status(item, "Paused"));
				if (["Draft", "Active", "Paused"].includes(item.status))
					button(__("Cancel agreement"), "data-cancel-agreement", () =>
						frappe.confirm(__("Cancel this agreement? This cannot be undone."), () =>
							this.status(item, "Cancelled")
						)
					);
				if (["Active", "Paused", "Expired"].includes(item.status) && !item.renewal)
					button(__("Create renewal"), "data-renew-agreement", () => this.renew(item));
			}
			this.app
				.content()
				.find("[data-schedule-visit]")
				.on("click", (event) => this.schedule(item, event.currentTarget.dataset.scheduleVisit));
		} catch (error) {
			this.app.renderError(error.message || __("Agreement could not load."));
		}
	}
	async status(item, status) {
		await this.call("set_status", { agreement_id: item.name, status, modified: item.modified });
		await this.open(item.name);
	}
	renew(item) {
		const dialog = new frappe.ui.Dialog({
			title: __("Create renewal draft"),
			fields: [
				{
					fieldname: "ends_on",
					fieldtype: "Date",
					label: __("New end date"),
					default: frappe.datetime.add_months(item.ends_on, 12),
					reqd: 1,
				},
			],
			primary_action_label: __("Create renewal"),
			primary_action: async (values) => {
				const result = await this.call("renew", {
					agreement_id: item.name,
					modified: item.modified,
					...values,
				});
				dialog.hide();
				await this.open(result.name);
			},
		});
		dialog.show();
	}
	async schedule(item, visit) {
		const options = await this.call("options", { customer_id: item.customer });
		if (!options.technicians.length) {
			frappe.msgprint(__("Add an active technician with an employee in this company first."));
			return;
		}
		const due = item.visits.find((v) => v.name === visit).due_on;
		const day = [due, frappe.datetime.get_today(), item.starts_on].sort().at(-1);
		const dialog = new frappe.ui.Dialog({
			title: __("Schedule maintenance visit"),
			fields: [
				{
					fieldname: "technician_id",
					fieldtype: "Select",
					label: __("Technician"),
					options: options.technicians.map((t) => ({ value: t.id, label: t.name })),
					default: options.technicians[0].id,
					reqd: 1,
				},
				{
					fieldname: "scheduled_for",
					fieldtype: "Datetime",
					label: __("Scheduled for"),
					default: day + " 09:00:00",
					reqd: 1,
				},
			],
			primary_action_label: __("Create service job"),
			primary_action: async (values) => {
				await this.call("schedule_visit", { visit_id: visit, ...values });
				dialog.hide();
				await this.open(item.name);
			},
		});
		dialog.show();
	}
};
