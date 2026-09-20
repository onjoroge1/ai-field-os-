frappe.provide("frappe.field_os");
frappe.field_os.Onboarding = class {
	constructor(app) {
		this.app = app;
	}
	async call(method, args = {}) {
		return (
			await frappe.call(`erpnext.field_os.api.onboarding.${method}`, {
				company: this.app.company,
				...args,
			})
		).message;
	}
	async open() {
		this.app.setHeading(__("Company setup"));
		this.app.setLoading();
		try {
			this.data = await this.call("get_setup");
			const d = this.data,
				e = frappe.utils.escape_html;
			this.app.content().html(
				`<section class="field-os__estimates" data-setup><div class="field-os__section-title"><h2>${e(
					d.company
				)}</h2><span data-setup-status>${e(d.status)}</span></div><p>${e(d.country)} · ${e(
					d.currency
				)} · ${__("Business hours use the site's time zone")}: ${e(
					d.timezone
				)}</p><div class="field-os__record-list">${[
					[
						"company",
						__("1. Locations and hours"),
						`${d.profile.locations?.length || 0} ${__("locations")}`,
					],
					["users", __("2. Team and roles"), `${d.users.length} ${__("configured team members")}`],
					["services", __("3. Service types and skills"), `${d.services.length} ${__("services")}`],
					[
						"notifications",
						__("4. Notification defaults"),
						d.notifications.preferred_channel || __("Choose defaults"),
					],
				]
					.map(
						([step, label, detail]) =>
							`<button data-setup-step="${step}"><strong>${
								d.steps.includes(step) ? "✓ " : ""
							}${e(label)}</strong><small>${e(detail)}</small><span>→</span></button>`
					)
					.join("")}</div><div>${d.users
					.map(
						(member) =>
							`<button class="btn btn-default btn-xs" data-setup-member="${e(
								member.email
							)}">${__("Edit")} ${e(member.first_name)}</button>`
					)
					.join(" ")}</div><h3>${__("Readiness checks")}</h3><ul>${d.checks
					.map(
						(c) =>
							`<li>${c.ok ? "✓" : c.required ? "○" : "—"} ${e(c.label)}${
								c.required ? "" : ` (${__("optional")})`
							}</li>`
					)
					.join("")}</ul><p>${__(
					"Integration checks verify saved sending configuration. Actual delivery is shown in Inbox after an approved message."
				)}</p><button class="btn btn-default btn-sm" data-setup-reload>${__(
					"Run checks"
				)}</button> <button class="btn btn-primary btn-sm" data-setup-finish ${
					d.checks.some((c) => c.required && !c.ok) ? "disabled" : ""
				}>${__("Finish setup")}</button>${
					d.system_manager
						? ` <button class="btn btn-default btn-sm" data-setup-create>${__(
								"Create company"
						  )}</button>`
						: ""
				}</section>`
			);
			const panel = this.app.content();
			panel
				.find("[data-setup-step]")
				.on("click", (event) => this[event.currentTarget.dataset.setupStep]());
			panel
				.find("[data-setup-member]")
				.on("click", (event) =>
					this.users(
						d.users.find((member) => member.email === event.currentTarget.dataset.setupMember)
					)
				);
			panel.find("[data-setup-reload]").on("click", () => this.open());
			panel.find("[data-setup-finish]").on("click", async () => {
				await this.call("complete", { version: d.version });
				this.open();
			});
			panel.find("[data-setup-create]").on("click", () => this.create());
		} catch (error) {
			this.app.renderError(error.message || __("Setup could not load."));
		}
	}
	form(title, fields, step, transform = (value) => value) {
		const version = this.data.version;
		const dialog = new frappe.ui.Dialog({
			title,
			size: "extra-large",
			fields,
			primary_action_label: __("Save and continue"),
			primary_action: async (values) => {
				dialog.disable_primary_action();
				try {
					await this.call("save_step", { step, values: transform(values), version });
					dialog.hide();
					this.open();
				} finally {
					dialog.enable_primary_action();
				}
			},
		});
		dialog.show();
		return dialog;
	}
	company() {
		const d = this.data.profile;
		this.form(
			__("Locations and business hours"),
			[
				{
					fieldname: "locations",
					fieldtype: "Table",
					label: __("Locations"),
					reqd: 1,
					in_place_edit: true,
					data: d.locations?.length
						? d.locations.map(({ name, ...row }) => ({ ...row, location_name: name }))
						: [{ location_name: __("Main office"), country: this.data.country }],
					fields: [
						{
							fieldname: "location_name",
							fieldtype: "Data",
							label: __("Location"),
							reqd: 1,
							in_list_view: 1,
							columns: 2,
						},
						{
							fieldname: "address_line1",
							fieldtype: "Data",
							label: __("Street address"),
							reqd: 1,
							in_list_view: 1,
							columns: 4,
						},
						{
							fieldname: "city",
							fieldtype: "Data",
							label: __("City"),
							reqd: 1,
							in_list_view: 1,
							columns: 2,
						},
						{
							fieldname: "country",
							fieldtype: "Data",
							label: __("Country"),
							reqd: 1,
							in_list_view: 1,
							columns: 2,
						},
						{ fieldname: "address", fieldtype: "Data", hidden: 1 },
					],
				},
				{
					fieldname: "days",
					fieldtype: "MultiCheck",
					sort_options: false,
					columns: 3,
					label: __("Business days"),
					options: [
						"Monday",
						"Tuesday",
						"Wednesday",
						"Thursday",
						"Friday",
						"Saturday",
						"Sunday",
					].map((label, i) => ({
						label: __(label),
						value: String(i),
						checked: (d.days || [0, 1, 2, 3, 4]).includes(i),
					})),
				},
				{
					fieldname: "opens",
					fieldtype: "Time",
					label: __("Opens"),
					reqd: 1,
					default: d.opens || "08:00:00",
				},
				{
					fieldname: "closes",
					fieldtype: "Time",
					label: __("Closes"),
					reqd: 1,
					default: d.closes || "18:00:00",
				},
			],
			"company",
			(values) => ({
				...values,
				days: values.days.map(Number),
				locations: values.locations.map((r) => ({
					name: r.location_name,
					address_line1: r.address_line1,
					city: r.city,
					country: r.country,
					address: r.address || null,
				})),
			})
		);
	}
	users(member = null) {
		const d = this.data;
		this.form(
			member ? __("Edit team member") : __("Add team member"),
			[
				{
					fieldname: "team",
					fieldtype: "HTML",
					options: `<p>${__(
						"New accounts are limited to this company. Share the initial password directly with the team member."
					)}</p><p>${
						d.users
							.map(
								(u) =>
									`${frappe.utils.escape_html(u.first_name)} · ${frappe.utils.escape_html(
										u.role
									)} · ${frappe.utils.escape_html(u.skills.join(", "))}`
							)
							.join("<br>") || __("No team members configured yet.")
					}</p>`,
				},
				{
					fieldname: "email",
					fieldtype: "Data",
					options: "Email",
					label: __("Email"),
					reqd: 1,
					default: member?.email,
					read_only: Boolean(member),
				},
				{
					fieldname: "first_name",
					fieldtype: "Data",
					label: __("Name"),
					reqd: 1,
					default: member?.first_name,
				},
				{
					fieldname: "role",
					fieldtype: "Select",
					label: __("Role"),
					options: [
						"Field OS Technician",
						"Field OS Dispatcher",
						"Field OS Manager",
						"Field OS Billing",
						"Field OS Owner",
					],
					default: member?.role || "Field OS Technician",
					reqd: 1,
				},
				{
					fieldname: "password",
					fieldtype: "Password",
					label: __("Initial password"),
					description: __(
						"At least twelve characters. The password is never shown in saved setup."
					),
					reqd: !member,
					hidden: Boolean(member),
				},
				{
					fieldname: "skills_text",
					fieldtype: "Data",
					label: __("Skills, separated by commas"),
					default: member?.skills.join(", ") || "Heating, Cooling",
					description: __("Use the same skill names when configuring service types."),
				},
				{
					fieldname: "gender",
					fieldtype: "Select",
					label: __("Gender for employee record"),
					options: ["", ...d.genders],
					depends_on: 'eval:doc.role === "Field OS Technician"',
				},
				{
					fieldname: "date_of_birth",
					fieldtype: "Date",
					label: __("Date of birth"),
					depends_on: 'eval:doc.role === "Field OS Technician"',
				},
				{
					fieldname: "date_of_joining",
					fieldtype: "Date",
					label: __("Joining date"),
					default: frappe.datetime.get_today(),
					depends_on: 'eval:doc.role === "Field OS Technician"',
				},
			],
			"users",
			(values) => {
				const { skills_text, team, ...row } = values;
				return {
					...row,
					skills: (skills_text || "")
						.split(",")
						.map((x) => x.trim())
						.filter(Boolean),
				};
			}
		);
	}
	services() {
		this.form(
			__("Service types and required skills"),
			[
				{
					fieldname: "services",
					fieldtype: "Table",
					label: __("Service types"),
					reqd: 1,
					in_place_edit: true,
					data: this.data.services.length
						? this.data.services.map(({ name, ...row }) => ({ ...row, service_name: name }))
						: [{ service_name: __("Heating tune-up"), rate: 125, skill: "Heating" }],
					fields: [
						{
							fieldname: "service_name",
							fieldtype: "Data",
							label: __("Service"),
							reqd: 1,
							in_list_view: 1,
							columns: 4,
						},
						{
							fieldname: "rate",
							fieldtype: "Float",
							precision: 2,
							label: `${__("Standard rate")} (${this.data.currency})`,
							reqd: 1,
							in_list_view: 1,
							columns: 2,
						},
						{
							fieldname: "skill",
							fieldtype: "Data",
							label: __("Required skill"),
							reqd: 1,
							in_list_view: 1,
							columns: 4,
						},
						{ fieldname: "item", fieldtype: "Data", hidden: 1 },
					],
				},
			],
			"services",
			(values) =>
				values.services.map((r) => ({
					name: r.service_name,
					rate: r.rate,
					skill: r.skill,
					item: r.item || null,
				}))
		);
	}
	notifications() {
		const d = this.data,
			n = d.notifications;
		this.form(
			__("Notification defaults"),
			[
				{
					fieldname: "help",
					fieldtype: "HTML",
					options: `<p>${__(
						"Choose an enabled company integration. Email and SMS account connections can be configured by your system administrator. Each customer message still requires operator approval."
					)}</p>`,
				},
				{
					fieldname: "preferred_channel",
					fieldtype: "Select",
					label: __("Preferred channel"),
					options: ["None", "Email", "SMS"],
					default: n.preferred_channel || "None",
					reqd: 1,
				},
				{
					fieldname: "email_integration",
					fieldtype: "Select",
					label: __("Default email mailbox"),
					options: [
						{ label: "", value: "" },
						...d.email_integrations.map((x) => ({ label: x.from_address, value: x.name })),
					],
					default: n.email_integration || "",
				},
				{
					fieldname: "sms_integration",
					fieldtype: "Select",
					label: __("Default SMS sender"),
					options: [
						{ label: "", value: "" },
						...d.sms_integrations.map((x) => ({ label: x.from_number, value: x.name })),
					],
					default: n.sms_integration || "",
				},
				{
					fieldname: "invoice_due_days",
					fieldtype: "Int",
					label: __("Invoice due after days"),
					default: n.invoice_due_days ?? 30,
					reqd: 1,
				},
			],
			"notifications",
			(values) => {
				const { help, ...row } = values;
				return row;
			}
		);
	}
	create() {
		const dialog = new frappe.ui.Dialog({
			title: __("Create company"),
			fields: [
				{ fieldname: "name", fieldtype: "Data", label: __("Company name"), reqd: 1 },
				{ fieldname: "abbreviation", fieldtype: "Data", label: __("Abbreviation"), reqd: 1 },
				{
					fieldname: "country",
					fieldtype: "Link",
					options: "Country",
					label: __("Country"),
					reqd: 1,
				},
				{
					fieldname: "currency",
					fieldtype: "Link",
					options: "Currency",
					label: __("Currency"),
					reqd: 1,
				},
			],
			primary_action_label: __("Create company"),
			primary_action: async (values) => {
				const result = await this.call("create_company", values);
				dialog.hide();
				this.app.company = result.company;
				await this.app.refresh();
				this.app.activeView = "setup";
				this.open();
			},
		});
		dialog.show();
	}
};
