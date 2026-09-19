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
			else this.renderComingSoon(event.currentTarget.textContent.trim());
		});
		this.root.on("click", "[data-doctype]", (event) => {
			frappe.set_route("Form", event.currentTarget.dataset.doctype, event.currentTarget.dataset.name);
		});
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
