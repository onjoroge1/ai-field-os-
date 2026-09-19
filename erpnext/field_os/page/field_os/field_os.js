frappe.pages["field-os"].on_page_load = function (wrapper) {
	frappe.require("/assets/erpnext/css/field_os.css", () => {
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
			else this.renderComingSoon(event.currentTarget.textContent.trim());
		});
		this.root.on("click", "[data-doctype]", (event) => {
			frappe.set_route("Form", event.currentTarget.dataset.doctype, event.currentTarget.dataset.name);
		});
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
		this.root.on("change", '[data-role="dispatch-day"]', (event) =>
			this.loadDispatch(event.target.value)
		);
		this.root.on("click", "[data-move-job]", (event) =>
			this.openDispatchChange(event.currentTarget.dataset.moveJob)
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
		return `<button class="field-os__attention-card severity-${
			item.severity
		}" data-doctype="${frappe.utils.escape_html(
			item.record.doctype
		)}" data-name="${frappe.utils.escape_html(item.record.record_id)}">
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
				<section><div class="field-os__section-title"><h2>${__("Equipment")}</h2><span>${
			data.equipment.length
		}</span></div><div class="field-os__record-list">${recordList(
			data.equipment,
			"Serial No",
			__("No equipment")
		)}</div></section>
				<section class="field-os__timeline"><div class="field-os__section-title"><h2>${__(
					"Unified timeline"
				)}</h2><span>${data.timeline.length}</span></div>${timeline}</section>
			</div>`);
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
