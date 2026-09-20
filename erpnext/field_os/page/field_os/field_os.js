frappe.pages["field-os"].on_page_load = function (wrapper) {
	frappe.require(["/assets/erpnext/css/field_os.css", "/assets/erpnext/js/field_os_estimates.js"], () => {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Field OS"), single_column: true });
		new FieldOSApp(page);
	});
};

class FieldOSApp {
	constructor(page) {
		this.page = page;
		this.company = frappe.defaults.get_default("company");
		this.activeView = "today";
		this.conversationId = null;
		this.lastQuestion = "";
		this.page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.renderFrame();
		this.estimates = new frappe.field_os.Estimates(this);
		this.bind();
		this.refresh();
	}

	renderFrame() {
		this.page.main.html(`
			<div class="field-os">
				<aside class="field-os__rail">
					<div class="field-os__brand"><span>F</span><strong>Field OS</strong></div>
					<nav data-role="nav"></nav>
				</aside>
				<main class="field-os__main">
					<header class="field-os__topbar">
						<div><p class="field-os__eyebrow">OPERATIONS</p><h1 data-role="heading">Today</h1></div>
						<label class="field-os__search"><span>⌕</span><input data-role="search" placeholder="Search customers, jobs, invoices…"></label>
					</header>
					<section data-role="search-results" class="field-os__search-results is-hidden"></section>
					<section data-role="content" aria-live="polite"><div class="field-os__loading">Loading operations…</div></section>
				</main>
			</div>`);
		this.root = this.page.main.find(".field-os");
	}

	bind() {
		let timer;
		let customerTimer;
		this.root.on("input", '[data-role="search"]', (event) => {
			clearTimeout(timer);
			timer = setTimeout(() => this.search(event.target.value), 220);
		});
		this.root.on("click", "[data-view]", (event) => {
			this.activeView = event.currentTarget.dataset.view;
			this.root.find("[data-view]").removeClass("is-active");
			$(event.currentTarget).addClass("is-active");
			if (this.activeView === "today") this.loadToday();
			else if (this.activeView === "ask") this.renderAsk();
			else if (this.activeView === "customers") this.renderCustomers();
			else if (this.activeView === "dispatch") this.renderDispatch();
			else if (this.activeView === "inbox") this.renderInbox();
			else this.renderComingSoon(event.currentTarget.textContent.trim());
		});
		this.root.on("click", "[data-doctype]", (event) => {
			frappe.set_route("Form", event.currentTarget.dataset.doctype, event.currentTarget.dataset.name);
		});
		this.root.on("click", "[data-open-inbox]", (event) =>
			this.openInbox(event.currentTarget.dataset.openInbox)
		);
		this.root.on("submit", '[data-role="ask-form"]', (event) => {
			event.preventDefault();
			this.ask($(event.currentTarget).find("textarea").val());
		});
		this.root.on("click", '[data-action="retry-ask"]', () => this.ask(this.lastQuestion));
		this.root.on("click", '[data-action="clear-chat"]', () => this.clearConversation());
		this.root.on("click", '[data-action="approve-proposal"]', (event) =>
			this.approveProposal(event.currentTarget.dataset.proposal)
		);
		this.root.on("click", '[data-action="reject-proposal"]', (event) =>
			this.rejectProposal(event.currentTarget.dataset.proposal)
		);
		this.root.on("input", '[data-role="customer-search"]', (event) => {
			clearTimeout(customerTimer);
			customerTimer = setTimeout(() => this.searchCustomers(event.target.value), 220);
		});
		this.root.on("click", "[data-customer]", (event) =>
			this.loadCustomer(event.currentTarget.dataset.customer)
		);
		this.root.on("click", "[data-equipment]", (event) =>
			this.loadEquipment(event.currentTarget.dataset.equipment)
		);
		this.root.on("click", '[data-action="new-equipment"]', () => this.editEquipment());
		this.root.on("click", '[data-action="edit-equipment"]', () =>
			this.editEquipment(this.equipmentHistory)
		);
		this.root.on("click", '[data-action="equipment-note"]', () => this.addEquipmentNote());
		this.root.on("change", '[data-role="dispatch-day"]', (event) =>
			this.loadDispatch(event.target.value)
		);
		this.root.on("click", "[data-move-job]", (event) =>
			this.openDispatchChange(event.currentTarget.dataset.moveJob)
		);
		this.root.on("change", '[data-role="inbox-filter"]', () => this.loadInbox());
		this.root.on("click", "[data-inbox-thread]", (event) =>
			this.loadInboxThread(event.currentTarget.dataset.inboxThread)
		);
		this.root.on("click", "[data-inbox-action]", (event) =>
			this.handleInboxAction(
				event.currentTarget.dataset.inboxAction,
				event.currentTarget.dataset.thread
			)
		);
		this.root.on("click", "[data-assign-thread]", (event) =>
			this.openInboxAssignment(event.currentTarget.dataset.assignThread)
		);
		this.root.on("click", "[data-thread-state]", (event) =>
			this.setInboxState(event.currentTarget.dataset.thread, event.currentTarget.dataset.threadState)
		);
		this.root.on("change", '[data-role="classification"]', (event) =>
			this.correctInbox(event.currentTarget.dataset.thread, "classification", event.target.value)
		);
	}

	async refresh() {
		if (!this.company) {
			this.renderError(__("Choose a default company before opening Field OS."));
			return;
		}
		try {
			const response = await frappe.call("erpnext.field_os.api.operator.bootstrap", {
				company: this.company,
			});
			this.session = response.message;
			this.renderNav();
			await this.loadToday();
		} catch (error) {
			this.renderError(error.message || __("Field OS could not load."));
		}
	}

	renderNav() {
		const icons = { today: "◫", ask: "✦", customers: "◎", dispatch: "↗", inbox: "✉" };
		this.root
			.find('[data-role="nav"]')
			.html(
				this.session.navigation
					.map(
						(item) =>
							`<button data-view="${item.id}" class="${
								item.id === this.activeView ? "is-active" : ""
							}"><span>${icons[item.id]}</span>${frappe.utils.escape_html(item.label)}</button>`
					)
					.join("")
			);
	}

	async loadToday() {
		this.setHeading(__("Today"));
		this.setLoading();
		try {
			const response = await frappe.call("erpnext.field_os.api.operator.today", {
				company: this.company,
			});
			this.renderToday(response.message);
		} catch (error) {
			this.renderError(error.message || __("Today's operations could not load."));
		}
	}

	renderToday(data) {
		const count = (key) => data.counts[key] || 0;
		const cards = [
			[__("Needs attention"), count("critical") + count("warning"), "warm"],
			[__("Jobs today"), count("today_jobs"), "blue"],
			[__("Unassigned"), count("unassigned"), "violet"],
			[__("Overdue"), count("overdue"), "red"],
		];
		const attention = data.attention.length
			? data.attention.map((item) => this.attentionCard(item)).join("")
			: `<div class="field-os__empty"><strong>${__("Nothing needs attention")}</strong><span>${__(
					"Operations are clear for now."
			  )}</span></div>`;
		this.content().html(`
			<div class="field-os__metrics">${cards
				.map(
					([label, value, tone]) =>
						`<article class="tone-${tone}"><span>${label}</span><strong>${value}</strong></article>`
				)
				.join("")}</div>
			<div class="field-os__section-title"><div><p class="field-os__eyebrow">EXCEPTIONS FIRST</p><h2>${__(
				"Attention queue"
			)}</h2></div><span>${data.attention.length} ${__("items")}</span></div>
			<div class="field-os__attention">${attention}</div>`);
	}

	attentionCard(item) {
		const due = item.due_at ? frappe.datetime.prettyDate(item.due_at) : __("Open");
		const target =
			item.kind === "inbox"
				? `data-open-inbox="${frappe.utils.escape_html(item.record.record_id)}"`
				: `data-doctype="${frappe.utils.escape_html(
						item.record.doctype
				  )}" data-name="${frappe.utils.escape_html(item.record.record_id)}"`;
		return `<button class="field-os__attention-card severity-${item.severity}" ${target}>
			<span class="field-os__signal"></span><span class="field-os__attention-copy"><strong>${frappe.utils.escape_html(
				item.title
			)}</strong><small>${frappe.utils.escape_html(
			item.summary
		)}</small></span><span class="field-os__due">${frappe.utils.escape_html(due)}<b>→</b></span>
		</button>`;
	}

	renderAsk() {
		this.setHeading(__("Ask Operations"));
		this.content().html(`
			<div class="field-os__ask">
				<div class="field-os__ask-intro"><span>✦</span><div><strong>${__(
					"Ask about the work, not the software"
				)}</strong><small>${__(
			"Answers use registered tools and link back to operational records."
		)}</small></div></div>
				<div class="field-os__chat" data-role="chat"><div class="field-os__assistant"><p>${__(
					"Try “Find Acme Dental” or “Show equipment for customer CUST-0042.”"
				)}</p></div></div>
				<form class="field-os__ask-form" data-role="ask-form">
					<textarea maxlength="4000" rows="2" placeholder="${__("Ask Field OS…")}" required></textarea>
					<div><label>${__("Keep conversation")} <select data-role="retention"><option value="session">${__(
			"This session"
		)}</option><option value="30_days">${__("30 days")}</option><option value="none">${__(
			"Don't retain"
		)}</option></select></label><span><button type="button" class="btn btn-default btn-sm" data-action="clear-chat">${__(
			"Clear"
		)}</button><button class="btn btn-primary btn-sm" type="submit">${__("Ask")}</button></span></div>
				</form>
			</div>`);
	}

	async ask(question) {
		question = (question || "").trim();
		if (!question) return;
		this.lastQuestion = question;
		const chat = this.root.find('[data-role="chat"]');
		chat.append(
			`<div class="field-os__user"><p>${frappe.utils.escape_html(
				question
			)}</p></div><div class="field-os__assistant is-thinking" data-role="thinking"><p>${__(
				"Checking operations…"
			)}</p></div>`
		);
		this.root.find('[data-role="ask-form"] textarea').val("");
		try {
			const response = await frappe.call("erpnext.field_os.api.ask.ask", {
				company: this.company,
				message: question,
				conversation_id: this.conversationId,
				retention: this.root.find('[data-role="retention"]').val(),
			});
			this.conversationId = response.message.conversation_id;
			this.root.find('[data-role="thinking"]').last().replaceWith(this.askResponse(response.message));
		} catch (error) {
			this.root
				.find('[data-role="thinking"]')
				.last()
				.replaceWith(
					`<div class="field-os__assistant field-os__answer-error"><strong>${__(
						"That request did not complete"
					)}</strong><p>${frappe.utils.escape_html(
						error.message || __("Ask Operations is unavailable.")
					)}</p><button class="btn btn-default btn-xs" data-action="retry-ask">${__(
						"Retry"
					)}</button></div>`
				);
		}
		chat.scrollTop(chat.prop("scrollHeight"));
	}

	askResponse(response) {
		const citations = (response.citations || [])
			.map(
				(item) =>
					`<button data-doctype="${frappe.utils.escape_html(
						item.doctype
					)}" data-name="${frappe.utils.escape_html(item.record_id)}">↗ ${frappe.utils.escape_html(
						item.label
					)}</button>`
			)
			.join("");
		const approval = response.approval
			? `<div class="field-os__approval"><p class="field-os__eyebrow">${__(
					"APPROVAL REQUIRED"
			  )} · ${frappe.utils.escape_html(response.approval.risk)}</p><strong>${frappe.utils.escape_html(
					response.approval.title
			  )}</strong><pre>${frappe.utils.escape_html(
					JSON.stringify(response.approval.arguments, null, 2)
			  )}</pre><div><button class="btn btn-default btn-xs" data-action="reject-proposal" data-proposal="${
					response.approval.proposal_id
			  }">${__(
					"Reject"
			  )}</button><button class="btn btn-primary btn-xs" data-action="approve-proposal" data-proposal="${
					response.approval.proposal_id
			  }">${__("Approve and run")}</button></div></div>`
			: "";
		return `<div class="field-os__assistant"><p>${frappe.utils.escape_html(response.answer)}</p>${
			citations ? `<div class="field-os__citations">${citations}</div>` : ""
		}${approval}</div>`;
	}

	async approveProposal(proposalId) {
		try {
			await frappe.call("erpnext.field_os.api.ask.approve", {
				company: this.company,
				proposal_id: proposalId,
				idempotency_key: `${proposalId}:${this.session.user}`,
			});
			this.root
				.find(`[data-proposal="${proposalId}"]`)
				.closest(".field-os__approval")
				.html(`<strong>${__("Approved and completed")}</strong>`);
		} catch (error) {
			frappe.msgprint({ title: __("Action not completed"), message: error.message, indicator: "red" });
		}
	}

	async rejectProposal(proposalId) {
		await frappe.call("erpnext.field_os.api.ask.reject", {
			company: this.company,
			proposal_id: proposalId,
		});
		this.root
			.find(`[data-proposal="${proposalId}"]`)
			.closest(".field-os__approval")
			.html(`<strong>${__("Rejected")}</strong>`);
	}

	async clearConversation() {
		if (this.conversationId)
			await frappe.call("erpnext.field_os.api.ask.clear_conversation", {
				company: this.company,
				conversation_id: this.conversationId,
			});
		this.conversationId = null;
		this.renderAsk();
	}

	renderCustomers() {
		this.setHeading(__("Customers"));
		this.content().html(`
			<div class="field-os__customer-finder">
				<div><p class="field-os__eyebrow">CUSTOMER · SITE · EQUIPMENT</p><h2>${__(
					"One operational history"
				)}</h2><p>${__(
			"Search for a customer to see open work, equipment, quotes, invoices, and every important event."
		)}</p></div>
				<input data-role="customer-search" placeholder="${__("Search customer name…")}">
				<div data-role="customer-results" class="field-os__customer-results"></div>
			</div>`);
	}

	async searchCustomers(query) {
		const panel = this.root.find('[data-role="customer-results"]');
		if (query.trim().length < 2) return panel.empty();
		panel.html(`<span>${__("Searching…")}</span>`);
		const response = await frappe.call("erpnext.field_os.api.operator.global_search", {
			company: this.company,
			query,
			limit: 12,
		});
		const customers = (response.message || []).filter((item) => item.kind === "customer");
		panel.html(
			customers.length
				? customers
						.map(
							(item) =>
								`<button data-customer="${frappe.utils.escape_html(
									item.record.record_id
								)}"><span>◎</span><strong>${frappe.utils.escape_html(
									item.title
								)}</strong><small>${frappe.utils.escape_html(
									item.subtitle
								)}</small><b>→</b></button>`
						)
						.join("")
				: `<span>${__("No tenant customers found.")}</span>`
		);
	}

	async loadCustomer(customerId) {
		this.setLoading();
		try {
			const response = await frappe.call("erpnext.field_os.api.customers.customer_360", {
				company: this.company,
				customer_id: customerId,
			});
			this.renderCustomer360(response.message);
		} catch (error) {
			this.renderError(error.message || __("Customer history could not load."));
		}
	}

	renderCustomer360(data) {
		this.currentCustomer = data;
		const customer = data.customer;
		const recordList = (items, doctype, empty) =>
			items.length
				? items
						.map(
							(item) =>
								`<button data-doctype="${doctype}" data-name="${frappe.utils.escape_html(
									item.id
								)}"><strong>${frappe.utils.escape_html(
									item.id
								)}</strong><small>${frappe.utils.escape_html(
									item.status || item.title || item.item_code || ""
								)}</small><span>→</span></button>`
						)
						.join("")
				: `<p class="text-muted">${empty}</p>`;
		const timeline = data.timeline.length
			? data.timeline
					.map(
						(item) =>
							`<button class="field-os__timeline-item" data-doctype="${
								item.doctype
							}" data-name="${frappe.utils.escape_html(item.record_id)}"><span class="kind-${
								item.kind
							}"></span><div><strong>${frappe.utils.escape_html(
								item.title
							)}</strong><small>${frappe.utils.escape_html(
								item.summary
							)}</small></div><time>${frappe.utils.escape_html(
								item.occurred_on || __("No date")
							)}</time></button>`
					)
					.join("")
			: `<p class="text-muted">${__("No operational history yet.")}</p>`;
		this.content().html(`
			<div class="field-os__customer-head"><button class="btn btn-default btn-xs" data-view="customers">← ${__(
				"Customers"
			)}</button><div><p class="field-os__eyebrow">CUSTOMER 360</p><h2>${frappe.utils.escape_html(
			customer.name
		)}</h2><p>${frappe.utils.escape_html(customer.email || __("No email"))} · ${frappe.utils.escape_html(
			customer.phone || __("No phone")
		)}</p></div><div><span>${__("Outstanding")}</span><strong>${frappe.utils.escape_html(
			String(data.total_outstanding)
		)}</strong></div></div>
			<div class="field-os__metrics field-os__metrics--three"><article class="tone-blue"><span>${__(
				"Open work"
			)}</span><strong>${
			data.open_work.length
		}</strong></article><article class="tone-violet"><span>${__("Open quotes")}</span><strong>${
			data.open_quotes.length
		}</strong></article><article class="tone-red"><span>${__("Open invoices")}</span><strong>${
			data.open_invoices.length
		}</strong></article></div>
			<div class="field-os__customer-grid">
				<section><div class="field-os__section-title"><h2>${__("Sites")}</h2><span>${
			data.sites.length
		}</span></div><div class="field-os__record-list">${recordList(
			data.sites,
			"Address",
			__("No sites")
		)}</div></section>
				<section><div class="field-os__section-title"><h2>${__("Equipment")}</h2>${
			this.session.capabilities.includes("dispatch")
				? `<button class="btn btn-default btn-xs" data-action="new-equipment">${__(
						"Add equipment"
				  )}</button>`
				: ""
		}</div><div class="field-os__record-list">${this.equipmentCards(
			data.hvac_equipment || []
		)}</div></section>
				<section class="field-os__timeline"><div class="field-os__section-title"><h2>${__(
					"Unified timeline"
				)}</h2><span>${data.timeline.length}</span></div>${timeline}</section>
			</div>`);
		this.estimates.renderCustomer(customer.id);
	}

	equipmentCards(items) {
		const e = frappe.utils.escape_html;
		return items.length
			? items
					.map(
						(item) =>
							`<button data-equipment="${e(item.id)}"><strong>${e(
								item.name
							)}</strong><small>${e(item.site_id)} · ${e(item.unit_type)} · ${e(
								item.status
							)}</small><span>→</span></button>`
					)
					.join("")
			: `<p class="text-muted">${__("No equipment at this customer yet.")}</p>`;
	}

	async loadEquipment(id) {
		this.setLoading();
		try {
			const response = await frappe.call("erpnext.field_os.api.equipment.history", {
				company: this.company,
				equipment_id: id,
			});
			this.equipmentHistory = response.message;
			this.renderEquipment(response.message);
		} catch (error) {
			this.renderError(error.message || __("Equipment history could not load."));
		}
	}

	renderEquipment(history) {
		const e = frappe.utils.escape_html;
		const item = history.equipment;
		this.setHeading(__("Equipment history"));
		const fields = [
			[__("Site"), item.site_id],
			[__("Unit type"), item.unit_type],
			[__("Manufacturer"), item.manufacturer],
			[__("Model"), item.model_number],
			[__("Serial number"), item.serial_number],
			[__("Installed"), item.installed_on],
			[__("Warranty expires"), item.warranty_expires_on],
			[__("Status"), item.status],
		];
		const photo = (url) =>
			typeof url === "string" && url.startsWith("/private/files/")
				? `<a href="${e(url)}" target="_blank" rel="noopener"><img src="${e(url)}" alt="${__(
						"Equipment service photo"
				  )}" loading="lazy"></a>`
				: "";
		this.content().html(`
			<div class="field-os__section-title"><div><button class="btn btn-default btn-xs" data-customer="${e(
				item.customer_id
			)}">← ${__("Customer")}</button><h2>${e(item.name)}</h2></div>
			${
				this.session.capabilities.includes("dispatch")
					? `<button class="btn btn-default" data-action="edit-equipment">${__(
							"Edit equipment"
					  )}</button>`
					: ""
			}</div>
			<dl class="field-os__equipment-details">${fields
				.map(([label, value]) => `<div><dt>${label}</dt><dd>${e(value || "—")}</dd></div>`)
				.join("")}</dl>
			<div class="field-os__customer-grid"><section><h3>${__(
				"Parent equipment"
			)}</h3><div class="field-os__record-list">${this.equipmentCards(
			history.ancestors
		)}</div></section>
			<section><h3>${__("Components")}</h3><div class="field-os__record-list">${this.equipmentCards(
			history.children
		)}</div></section></div>
			<div class="field-os__section-title"><h2>${__("Service notes")}</h2>${
			this.session.capabilities.includes("field_update")
				? `<button class="btn btn-primary" data-action="equipment-note">${__(
						"Add service note"
				  )}</button>`
				: ""
		}</div>
			<div class="field-os__equipment-notes">${
				history.notes.length
					? history.notes
							.map(
								(note) =>
									`<article><div><strong>${e(note.technician)}</strong><time>${e(
										note.occurred_at
									)}</time></div><p>${e(window.strip_html(note.note))}</p>${
										note.visit_id
											? `<button class="btn btn-link" data-doctype="Maintenance Visit" data-name="${e(
													note.visit_id
											  )}">${e(note.visit_id)}</button>`
											: ""
									}<div class="field-os__equipment-photos">${note.photo_urls
										.map(photo)
										.join("")}</div></article>`
							)
							.join("")
					: `<p class="text-muted">${__(
							"No service notes yet. Record the first inspection or repair."
					  )}</p>`
			}</div>`);
	}

	async editEquipment(history = null) {
		const item = history?.equipment;
		if (!this.currentCustomer || (item && this.currentCustomer.customer.id !== item.customer_id)) {
			const response = await frappe.call("erpnext.field_os.api.customers.customer_360", {
				company: this.company,
				customer_id: item.customer_id,
			});
			this.currentCustomer = response.message;
		}
		const customer = this.currentCustomer;
		const fields = [
			{
				fieldname: "site",
				fieldtype: "Select",
				label: __("Site"),
				options: customer.sites.map((site) => ({ value: site.id, label: site.title })),
				reqd: 1,
				read_only: !!item,
				default: item?.site_id,
			},
			{
				fieldname: "equipment_name",
				fieldtype: "Data",
				label: __("Equipment name"),
				reqd: 1,
				default: item?.name,
			},
			{
				fieldname: "unit_type",
				fieldtype: "Data",
				label: __("Unit type"),
				reqd: 1,
				default: item?.unit_type,
			},
			...["manufacturer", "model_number", "serial_number"].map((fieldname) => ({
				fieldname,
				fieldtype: "Data",
				label: __(frappe.model.unscrub(fieldname)),
				default: item?.[fieldname],
			})),
			{
				fieldname: "installed_on",
				fieldtype: "Date",
				label: __("Installed on"),
				default: item?.installed_on,
			},
			{
				fieldname: "warranty_expires_on",
				fieldtype: "Date",
				label: __("Warranty expires on"),
				default: item?.warranty_expires_on,
			},
			{
				fieldname: "parent_equipment",
				fieldtype: "Select",
				label: __("Parent equipment"),
				options: [
					"",
					...(customer.hvac_equipment || [])
						.filter((other) => other.id !== item?.id)
						.map((other) => ({ value: other.id, label: `${other.name} · ${other.site_id}` })),
				],
				default: item?.parent_id,
			},
			{
				fieldname: "status",
				fieldtype: "Select",
				label: __("Status"),
				options: ["Active", "Inactive", "Replaced", "Retired"],
				default: item?.status || "Active",
				reqd: 1,
			},
		];
		const dialog = new frappe.ui.Dialog({
			title: item ? __("Edit equipment") : __("Add equipment"),
			fields,
			primary_action_label: __("Save"),
			primary_action: async (values) => {
				const { site, ...details } = values;
				dialog.disable_primary_action();
				try {
					const response = await frappe.call("erpnext.field_os.api.equipment.save_equipment", {
						company: this.company,
						customer_id: customer.customer.id,
						site_id: site,
						values: details,
						equipment_id: item?.id,
						modified: history?.modified,
					});
					dialog.hide();
					await this.loadEquipment(response.message.name);
				} finally {
					dialog.enable_primary_action();
				}
			},
		});
		dialog.show();
	}

	addEquipmentNote() {
		const equipment = this.equipmentHistory.equipment;
		const photos = [];
		const dialog = new frappe.ui.Dialog({
			title: __("Add service note"),
			fields: [
				{
					fieldname: "note",
					fieldtype: "Small Text",
					label: __("Inspection or repair notes"),
					reqd: 1,
				},
				{
					fieldname: "visit",
					fieldtype: "Select",
					options: [
						"",
						...this.equipmentHistory.visits.map((visit) => ({
							value: visit.name,
							label: `${visit.name} · ${visit.mntc_date}`,
						})),
					],
					label: __("Service visit"),
				},
				{
					fieldname: "photos",
					fieldtype: "HTML",
					options: `<label>${__(
						"Photos (optional, up to 20)"
					)}</label><input type="file" accept="image/jpeg,image/png,image/webp" multiple data-equipment-photos><p data-upload-status aria-live="polite"></p>`,
				},
			],
			primary_action_label: __("Save service note"),
			primary_action: async (values) => {
				dialog.disable_primary_action();
				try {
					await frappe.call("erpnext.field_os.api.equipment.add_note", {
						company: this.company,
						equipment_id: equipment.id,
						note: values.note,
						visit_id: values.visit,
						photo_urls: photos,
					});
					dialog.hide();
					await this.loadEquipment(equipment.id);
				} finally {
					dialog.enable_primary_action();
				}
			},
		});
		dialog.fields_dict.photos.$wrapper.on("change", "input", async (event) => {
			const files = Array.from(event.target.files);
			if (photos.length + files.length > 20 || files.some((file) => file.size > 5000000)) {
				frappe.msgprint(__("Choose at most 20 photos, each smaller than 5 MB."));
				return;
			}
			dialog.disable_primary_action();
			event.target.disabled = true;
			try {
				for (const file of files) {
					const content = await new Promise((resolve, reject) => {
						const reader = new FileReader();
						reader.onload = () => resolve(reader.result.split(",")[1]);
						reader.onerror = reject;
						reader.readAsDataURL(file);
					});
					const response = await frappe.call("erpnext.field_os.api.equipment.upload_photo", {
						company: this.company,
						equipment_id: equipment.id,
						content,
					});
					photos.push(response.message.file_url);
				}
			} finally {
				dialog.fields_dict.photos.$wrapper
					.find("[data-upload-status]")
					.text(__("{0} photos uploaded", [photos.length]));
				dialog.enable_primary_action();
				event.target.disabled = false;
				event.target.value = "";
			}
		});
		dialog.show();
	}

	renderDispatch() {
		this.setHeading(__("Dispatch"));
		const today = frappe.datetime.get_today();
		this.content().html(
			`<div class="field-os__dispatch-toolbar"><div><p class="field-os__eyebrow">LIVE OPERATIONS</p><h2>${__(
				"Jobs and technicians"
			)}</h2></div><label>${__(
				"Day"
			)} <input type="date" data-role="dispatch-day" value="${today}"></label></div><div data-role="dispatch-board" class="field-os__loading">${__(
				"Loading dispatch…"
			)}</div>`
		);
		this.loadDispatch(today);
	}

	async loadDispatch(day) {
		const board = this.root.find('[data-role="dispatch-board"]');
		try {
			const response = await frappe.call("erpnext.field_os.api.dispatch.board", {
				company: this.company,
				day,
			});
			this.dispatchData = response.message;
			this.renderDispatchBoard(response.message);
		} catch (error) {
			board
				.attr("class", "field-os__error")
				.html(
					`<strong>${__("Dispatch unavailable")}</strong><span>${frappe.utils.escape_html(
						error.message
					)}</span>`
				);
		}
	}

	renderDispatchBoard(data) {
		const conflictJobs = new Set((data.conflicts || []).flatMap((item) => item.job_ids));
		const columns = [{ id: "", name: __("Unassigned"), status: "attention" }, ...data.technicians];
		const html = columns
			.map((technician) => {
				const jobs = data.jobs.filter((job) => (job.technician_id || "") === technician.id);
				return `<section class="field-os__dispatch-column"><header><div><span class="field-os__tech-status status-${
					technician.status
				}"></span><strong>${frappe.utils.escape_html(technician.name)}</strong></div><small>${
					technician.status === "busy" ? __("On job") : jobs.length + " " + __("jobs")
				}</small></header><div>${
					jobs.length
						? jobs.map((job) => this.dispatchCard(job, conflictJobs.has(job.id))).join("")
						: `<p class="field-os__column-empty">${__("No jobs")}</p>`
				}</div></section>`;
			})
			.join("");
		this.root.find('[data-role="dispatch-board"]').attr("class", "field-os__dispatch-board").html(html);
	}

	dispatchCard(job, conflict) {
		const start = moment(job.start).format("h:mm A");
		const end = moment(job.end).format("h:mm A");
		const canMove = (this.session.capabilities || []).includes("dispatch");
		return `<article class="field-os__job-card ${
			conflict ? "has-conflict" : ""
		}"><div><time>${start}–${end}</time>${
			conflict ? `<span>${__("Conflict")}</span>` : ""
		}</div><strong>${frappe.utils.escape_html(job.customer_name)}</strong><p>${frappe.utils.escape_html(
			job.summary
		)}</p><footer><small>${frappe.utils.escape_html(job.status)}</small>${
			canMove
				? `<button data-move-job="${frappe.utils.escape_html(job.id)}">${__("Move")} ↗</button>`
				: `<button data-doctype="Maintenance Visit" data-name="${frappe.utils.escape_html(
						job.id
				  )}">${__("Open")} ↗</button>`
		}</footer></article>`;
	}

	openDispatchChange(jobId) {
		const job = this.dispatchData.jobs.find((item) => item.id === jobId);
		const dialog = new frappe.ui.Dialog({
			title: __("Reschedule or reassign {0}", [jobId]),
			fields: [
				{
					fieldname: "technician_id",
					label: __("Technician"),
					fieldtype: "Select",
					options: this.dispatchData.technicians.map((item) => ({
						label: item.name,
						value: item.id,
					})),
					default: job.technician_id,
					reqd: 1,
				},
				{
					fieldname: "start",
					label: __("Start"),
					fieldtype: "Datetime",
					default: job.start,
					reqd: 1,
				},
				{ fieldname: "end", label: __("End"), fieldtype: "Datetime", default: job.end, reqd: 1 },
			],
			primary_action_label: __("Check and move"),
			primary_action: async (values) => {
				dialog.get_primary_btn().prop("disabled", true);
				try {
					const previewResponse = await frappe.call(
						"erpnext.field_os.api.dispatch.preview_change",
						{
							company: this.company,
							job_id: job.id,
							technician_id: values.technician_id,
							start: moment(values.start).toISOString(),
							end: moment(values.end).toISOString(),
							expected_version: job.version,
						}
					);
					const preview = previewResponse.message;
					if (!preview.can_commit) {
						frappe.msgprint({
							title: __("Schedule conflict"),
							message: __(
								"This technician already has an overlapping job. Choose another time or technician."
							),
							indicator: "orange",
						});
						return;
					}
					const result = await frappe.call("erpnext.field_os.api.dispatch.commit_change", {
						company: this.company,
						proposal_id: preview.proposal.id,
						idempotency_key: `dispatch:${preview.proposal.id}:${this.session.user}`,
					});
					dialog.hide();
					frappe.show_alert({ message: __("Dispatch updated"), indicator: "green" });
					this.loadDispatch(this.root.find('[data-role="dispatch-day"]').val());
				} catch (error) {
					frappe.msgprint({ title: __("Move failed"), message: error.message, indicator: "red" });
				} finally {
					dialog.get_primary_btn().prop("disabled", false);
				}
			},
		});
		dialog.show();
	}

	openInbox(threadId) {
		this.activeView = "inbox";
		this.root.find("[data-view]").removeClass("is-active");
		this.root.find('[data-view="inbox"]').addClass("is-active");
		this.renderInbox(threadId);
	}

	renderInbox(threadId = null) {
		this.setHeading(__("Inbox"));
		this.content().html(`
			<div class="field-os__inbox-toolbar">
				<div><p class="field-os__eyebrow">EMAIL · SMS · WEB · FIELD</p><h2>${__("Operational Inbox")}</h2></div>
				<div><select data-role="inbox-filter" data-filter="channel"><option value="">${__(
					"All channels"
				)}</option><option value="email">Email</option><option value="sms">SMS</option><option value="web">Web</option><option value="technician_note">${__(
			"Technician notes"
		)}</option></select><select data-role="inbox-filter" data-filter="assignment"><option value="all">${__(
			"Everyone"
		)}</option><option value="mine">${__("Mine")}</option><option value="unassigned">${__(
			"Unassigned"
		)}</option></select></div>
			</div>
			<div class="field-os__inbox"><section><div class="field-os__inbox-counts" data-role="inbox-counts"></div><div class="field-os__inbox-list" data-role="inbox-list"><div class="field-os__loading">${__(
				"Loading Inbox…"
			)}</div></div></section><section class="field-os__thread-pane" data-role="thread-pane"><div class="field-os__empty"><strong>${__(
			"Choose a conversation"
		)}</strong><span>${__("Messages and suggested actions appear here.")}</span></div></section></div>`);
		this.loadInbox(threadId);
	}

	async loadInbox(preferredThreadId = null) {
		const channel = this.root.find('[data-filter="channel"]').val() || null;
		const assignment = this.root.find('[data-filter="assignment"]').val() || "all";
		try {
			const response = await frappe.call("erpnext.field_os.api.inbox.queue", {
				company: this.company,
				channel,
				assignment,
			});
			const data = response.message;
			this.inboxData = data;
			this.root
				.find('[data-role="inbox-counts"]')
				.html(
					`<span>${data.counts.total || 0} ${__("open")}</span><span class="is-overdue">${
						data.counts.overdue || 0
					} ${__("overdue")}</span><span>${data.counts.unassigned || 0} ${__("unassigned")}</span>`
				);
			this.root
				.find('[data-role="inbox-list"]')
				.html(
					data.items.length
						? data.items.map((item) => this.inboxListItem(item)).join("")
						: `<div class="field-os__empty"><strong>${__("Inbox clear")}</strong><span>${__(
								"No conversations match these filters."
						  )}</span></div>`
				);
			const selectedThread = preferredThreadId || (data.items.length ? data.items[0].thread.id : null);
			if (selectedThread) this.loadInboxThread(selectedThread);
		} catch (error) {
			this.root
				.find('[data-role="inbox-list"]')
				.html(
					`<div class="field-os__error"><strong>${__(
						"Inbox unavailable"
					)}</strong><span>${frappe.utils.escape_html(error.message)}</span></div>`
				);
		}
	}

	inboxListItem(item) {
		const message = item.latest_message;
		const preview = message ? message.body.slice(0, 115) : __("No messages yet");
		const age =
			item.age_seconds < 3600
				? `${Math.max(1, Math.floor(item.age_seconds / 60))}m`
				: item.age_seconds < 86400
				? `${Math.floor(item.age_seconds / 3600)}h`
				: `${Math.floor(item.age_seconds / 86400)}d`;
		return `<button class="field-os__inbox-item sla-${
			item.sla_state
		}" data-inbox-thread="${frappe.utils.escape_html(
			item.thread.id
		)}"><span class="field-os__channel channel-${frappe.utils.escape_html(item.thread.channel)}">${
			item.thread.channel === "email" ? "✉" : item.thread.channel === "sms" ? "▣" : "•"
		}</span><span><strong>${frappe.utils.escape_html(
			item.thread.subject
		)}</strong><small>${frappe.utils.escape_html(preview)}</small><em>${frappe.utils.escape_html(
			item.thread.classification || __("unclassified")
		)}${
			item.thread.assigned_to
				? ` · ${frappe.utils.escape_html(item.thread.assigned_to)}`
				: ` · ${__("unassigned")}`
		}</em></span><time>${age}</time></button>`;
	}

	async loadInboxThread(threadId) {
		this.selectedThread = threadId;
		this.root.find("[data-inbox-thread]").removeClass("is-active");
		this.root.find(`[data-inbox-thread="${threadId}"]`).addClass("is-active");
		const pane = this.root
			.find('[data-role="thread-pane"]')
			.html(`<div class="field-os__loading">${__("Loading conversation…")}</div>`);
		try {
			const response = await frappe.call("erpnext.field_os.api.inbox.thread", {
				company: this.company,
				thread_id: threadId,
			});
			this.renderInboxThread(response.message);
		} catch (error) {
			pane.html(
				`<div class="field-os__error"><strong>${__(
					"Conversation unavailable"
				)}</strong><span>${frappe.utils.escape_html(error.message)}</span></div>`
			);
		}
	}

	renderInboxThread(data) {
		const thread = data.thread;
		const classifications = [
			"general",
			"service_request",
			"billing",
			"safety_emergency",
			"spam",
			"consent",
		];
		const messages = data.messages
			.map(
				(message) =>
					`<article class="field-os__message direction-${
						message.direction
					}"><header><strong>${frappe.utils.escape_html(
						message.sender.display_name || message.sender.address
					)}</strong><time>${frappe.datetime.prettyDate(
						message.occurred_at
					)}</time></header><p>${frappe.utils.escape_html(
						message.body
					)}</p><footer><span>${frappe.utils.escape_html(
						message.channel
					)}</span><span class="delivery-${message.delivery_state}">${frappe.utils.escape_html(
						message.delivery_state
					)}</span>${
						message.attachments.length ? `<span>📎 ${message.attachments.length}</span>` : ""
					}</footer></article>`
			)
			.join("");
		const threadId = frappe.utils.escape_html(thread.id);
		const suggestions = data.suggestions
			.map(
				(action) =>
					`<button data-inbox-action="${frappe.utils.escape_html(
						action.kind
					)}" data-thread="${threadId}">${frappe.utils.escape_html(action.label)}</button>`
			)
			.join("");
		this.root.find('[data-role="thread-pane"]').html(`
			<header class="field-os__thread-head"><div><p class="field-os__eyebrow">${frappe.utils.escape_html(
				thread.channel.toUpperCase()
			)} · ${frappe.utils.escape_html(thread.state.toUpperCase())}</p><h2>${frappe.utils.escape_html(
			thread.subject
		)}</h2><span>${
			thread.assigned_to
				? `${__("Assigned to")} ${frappe.utils.escape_html(thread.assigned_to)}`
				: __("Unassigned")
		}</span></div><div><button class="btn btn-default btn-xs" data-assign-thread="${threadId}">${
			thread.assigned_to ? __("Reassign") : __("Assign")
		}</button><button class="btn btn-default btn-xs" data-thread-state="${
			thread.state === "closed" ? "open" : "closed"
		}" data-thread="${threadId}">${
			thread.state === "closed" ? __("Reopen") : __("Close")
		}</button></div></header>
			<div class="field-os__thread-context"><label>${__(
				"Classification"
			)} <select data-role="classification" data-thread="${threadId}">${classifications
			.map(
				(value) =>
					`<option value="${value}" ${
						value === thread.classification ? "selected" : ""
					}>${value.replaceAll("_", " ")}</option>`
			)
			.join("")}</select></label>${
			thread.links.customer_id
				? `<button data-customer="${frappe.utils.escape_html(
						thread.links.customer_id
				  )}">◎ ${frappe.utils.escape_html(thread.links.customer_id)}</button>`
				: `<span>${__("No customer linked")}</span>`
		}${
			thread.links.service_request_id
				? `<button data-doctype="Issue" data-name="${frappe.utils.escape_html(
						thread.links.service_request_id
				  )}">↗ ${frappe.utils.escape_html(thread.links.service_request_id)}</button>`
				: ""
		}</div>
			<div class="field-os__messages">${messages || `<p class="text-muted">${__("No messages")}</p>`}</div>
			<div class="field-os__suggestions"><p class="field-os__eyebrow">${__("SUGGESTED ACTIONS")}</p><div>${
			suggestions || `<span>${__("No suggestions")}</span>`
		}</div></div>`);
	}

	async handleInboxAction(action, threadId) {
		try {
			if (action === "assign") {
				await frappe.call("erpnext.field_os.api.inbox.assign", {
					company: this.company,
					thread_id: threadId,
					user: this.session.user,
					idempotency_key: this.actionKey("assign", threadId),
				});
				this.loadInbox();
			} else if (action === "reply") {
				this.openInboxReply(threadId);
			} else if (action === "correct") {
				this.openCustomerCorrection(threadId);
			} else if (action === "create_request") {
				await frappe.call("erpnext.field_os.api.inbox.create_service_request", {
					company: this.company,
					thread_id: threadId,
					idempotency_key: this.actionKey("request", threadId),
				});
				frappe.show_alert({ message: __("Service request created"), indicator: "green" });
				this.loadInboxThread(threadId);
			} else if (action === "escalate") {
				const item = (this.inboxData.items || []).find(
					(candidate) => candidate.thread.id === threadId
				);
				if (item && item.thread.assigned_to && item.thread.assigned_to !== this.session.user) {
					frappe.msgprint({
						title: __("Safety issue already assigned"),
						message: `${__("Assigned to")} ${frappe.utils.escape_html(item.thread.assigned_to)}`,
						indicator: "orange",
					});
					return;
				}
				await frappe.call("erpnext.field_os.api.inbox.assign", {
					company: this.company,
					thread_id: threadId,
					user: this.session.user,
					idempotency_key: this.actionKey("escalate", threadId),
				});
				frappe.show_alert({ message: __("Safety issue assigned to you"), indicator: "orange" });
				this.loadInbox();
			} else if (action === "open_message") {
				const item = (this.inboxData.items || []).find(
					(candidate) => candidate.thread.id === threadId
				);
				if (item && item.latest_message)
					frappe.set_route("Form", "Field OS Communication Message", item.latest_message.id);
			}
		} catch (error) {
			frappe.msgprint({ title: __("Inbox action failed"), message: error.message, indicator: "red" });
		}
	}

	openInboxAssignment(threadId) {
		const dialog = new frappe.ui.Dialog({
			title: __("Assign conversation"),
			fields: [
				{
					fieldname: "user",
					fieldtype: "Link",
					options: "User",
					label: __("Assignee"),
					default: this.session.user,
					reqd: 1,
				},
			],
			primary_action_label: __("Assign"),
			primary_action: async (values) => {
				try {
					await frappe.call("erpnext.field_os.api.inbox.assign", {
						company: this.company,
						thread_id: threadId,
						user: values.user,
						idempotency_key: this.actionKey("assign", threadId),
					});
					dialog.hide();
					frappe.show_alert({ message: __("Conversation assigned"), indicator: "green" });
					this.loadInbox();
				} catch (error) {
					frappe.msgprint({
						title: __("Assignment failed"),
						message: error.message,
						indicator: "red",
					});
				}
			},
		});
		dialog.show();
	}

	openInboxReply(threadId) {
		const dialog = new frappe.ui.Dialog({
			title: __("Reply to customer"),
			fields: [
				{ fieldname: "subject", fieldtype: "Data", label: __("Subject (email only)") },
				{ fieldname: "body", fieldtype: "Small Text", label: __("Message"), reqd: 1 },
			],
			primary_action_label: __("Review and send"),
			primary_action: (values) => {
				frappe.confirm(
					`${__(
						"Send this customer message?"
					)}<br><br><div class="well well-sm">${frappe.utils.escape_html(values.body)}</div>`,
					async () => {
						try {
							const prepared = (
								await frappe.call("erpnext.field_os.api.inbox.prepare_reply", {
									company: this.company,
									thread_id: threadId,
									body: values.body,
									subject: values.subject,
								})
							).message;
							const method =
								prepared.channel === "email"
									? "erpnext.field_os.api.email.approve_send"
									: "erpnext.field_os.api.sms.approve_send";
							await frappe.call(method, {
								company: this.company,
								proposal_id: prepared.proposal.id,
								integration_id: prepared.integration_id,
								idempotency_key: `reply:${prepared.message_id}`,
							});
							dialog.hide();
							frappe.show_alert({ message: __("Message sent"), indicator: "green" });
							this.loadInboxThread(threadId);
						} catch (error) {
							frappe.msgprint({
								title: __("Message not sent"),
								message: error.message,
								indicator: "red",
							});
						}
					}
				);
			},
		});
		dialog.show();
	}

	openCustomerCorrection(threadId) {
		const dialog = new frappe.ui.Dialog({
			title: __("Link customer"),
			fields: [
				{
					fieldname: "customer",
					fieldtype: "Link",
					options: "Customer",
					label: __("Customer"),
					reqd: 1,
				},
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Why was the suggestion wrong?") },
			],
			primary_action_label: __("Link and teach Field OS"),
			primary_action: async (values) => {
				try {
					await frappe.call("erpnext.field_os.api.inbox.correct", {
						company: this.company,
						thread_id: threadId,
						field: "customer_id",
						value: values.customer,
						reason: values.reason,
					});
					dialog.hide();
					this.loadInboxThread(threadId);
				} catch (error) {
					frappe.msgprint({
						title: __("Customer not linked"),
						message: error.message,
						indicator: "red",
					});
				}
			},
		});
		dialog.show();
	}

	async correctInbox(threadId, field, value) {
		try {
			await frappe.call("erpnext.field_os.api.inbox.correct", {
				company: this.company,
				thread_id: threadId,
				field,
				value,
				reason: "operator correction",
			});
			frappe.show_alert({ message: __("Correction saved for evaluation"), indicator: "green" });
			this.loadInboxThread(threadId);
		} catch (error) {
			frappe.msgprint({ title: __("Correction not saved"), message: error.message, indicator: "red" });
			this.loadInboxThread(threadId);
		}
	}

	async setInboxState(threadId, state) {
		try {
			await frappe.call("erpnext.field_os.api.inbox.set_state", {
				company: this.company,
				thread_id: threadId,
				state,
				idempotency_key: this.actionKey(`state:${state}`, threadId),
			});
			this.loadInbox();
		} catch (error) {
			frappe.msgprint({ title: __("State not changed"), message: error.message, indicator: "red" });
		}
	}

	actionKey(action, threadId) {
		return `${action}:${this.company}:${threadId}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
	}

	async search(query) {
		const panel = this.root.find('[data-role="search-results"]');
		if (query.trim().length < 2) return panel.addClass("is-hidden").empty();
		const response = await frappe.call("erpnext.field_os.api.operator.global_search", {
			company: this.company,
			query,
		});
		const results = response.message || [];
		panel
			.html(
				results.length
					? results
							.map(
								(item) =>
									`<button data-doctype="${item.record.doctype}" data-name="${
										item.record.record_id
									}"><span class="field-os__result-kind">${frappe.utils.escape_html(
										item.kind
									)}</span><strong>${frappe.utils.escape_html(
										item.title
									)}</strong><small>${frappe.utils.escape_html(
										item.subtitle
									)}</small></button>`
							)
							.join("")
					: `<p>${__("No matching operational records.")}</p>`
			)
			.removeClass("is-hidden");
	}

	renderComingSoon(label) {
		this.setHeading(label);
		this.content().html(
			`<div class="field-os__empty"><strong>${frappe.utils.escape_html(label)}</strong><span>${__(
				"This workspace arrives in the next stacked PR."
			)}</span></div>`
		);
	}

	setHeading(value) {
		this.root.find('[data-role="heading"]').text(value);
	}
	content() {
		return this.root.find('[data-role="content"]');
	}
	setLoading() {
		this.content().html(`<div class="field-os__loading">${__("Loading operations…")}</div>`);
	}
	renderError(message) {
		this.content().html(
			`<div class="field-os__error"><strong>${__(
				"Unable to load"
			)}</strong><span>${frappe.utils.escape_html(message)}</span></div>`
		);
	}
}
