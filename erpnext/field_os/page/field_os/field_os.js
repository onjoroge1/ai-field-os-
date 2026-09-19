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
