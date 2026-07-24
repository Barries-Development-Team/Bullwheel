// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

frappe.provide('bullwheel.forms');

// Hosts a full frappe.ui.form.Form (toolbar, script_manager, depends_on evaluation — everything
// Quick Entry lacks) inside a frappe.ui.Dialog. The modal backdrop covers the desk navbar and
// workspace sidebar, so the form presents as a focused popup without routing away from the
// current page. Built for New Product creation, but doctype-agnostic.
class FormDialog {
	// options.seed_document: optional pre-populated locals document (from frappe.model.get_new_doc).
	// options.after_insert: called with the saved document after a successful save closes the dialog.
	constructor(doctype, options = {}) {
		this.doctype = doctype;
		this.seed_document = options.seed_document || null;
		this.after_insert = options.after_insert || null;
		this.discard_confirmed = false;
		this.teardown_completed = false;
	}

	// Loads the doctype metadata and client scripts, then builds and shows the dialog form.
	// with_doctype also evaluates the doctype's form script, which registers the
	// frappe.ui.form.on handlers that this dialog exists to support.
	open() {
		frappe.model.with_doctype(this.doctype, () => {
			if (!this.seed_document) {
				this.seed_document = frappe.model.get_new_doc(this.doctype);
			}
			this.build_dialog();
			// Show before constructing the Form so it renders into visible DOM.
			this.dialog.show();
			this.build_and_refresh_form();
			this.install_after_save_handler();
		});
	}

	// Constructs the hosting Dialog with no fields of its own — the Form supplies the entire
	// body, and the Form's page head carries the Save button, so the dialog footer is hidden
	// to avoid a duplicate primary action.
	build_dialog() {
		this.dialog = new frappe.ui.Dialog({
			title: __('New {0}', [__(this.doctype)]),
			onhide: () => this.handle_hide(),
		});
		// Dialog only offers modal-sm/lg/xl; xl is too narrow for a multi-column form layout,
		// so a custom class (styled in public/css/utilities.bundle.css) makes it near-fullscreen.
		this.dialog.$wrapper.addClass('bullwheel-form-dialog');
		this.dialog.footer.addClass('hide');
	}

	// Constructs the real frappe.ui.form.Form inside the dialog body and renders the seeded
	// document into it. in_form = false is the framework's escape hatch for out-of-page forms:
	// it suppresses the save-triggered route change (rename_notify) and the browser
	// title write (refresh_header) — but NOT the breadcrumb calls, which need a separate
	// guard below.
	build_and_refresh_form() {
		this.form_container = document.createElement('div');
		this.dialog.body.appendChild(this.form_container);

		this.form = new frappe.ui.form.Form(this.doctype, this.form_container, false);

		// Form.refresh sets the global cur_frm, and the Page built during Form.setup overwrites
		// frappe.ui.pages for the *current* route. Snapshot both and restore them right after
		// this synchronous call returns. cur_frm matters beyond convenience: Frappe's realtime
		// doc_update listener (frappe/model/model.js) routes entirely off cur_frm.doc.doctype/name
		// — if it's left pointing at this dialog's phantom document, a doc_update for whatever
		// document is actually open *behind* the modal (e.g. an Order Receipt a background scan
		// job just saved) takes the listener's "different document" branch and purges that
		// document from locals instead of quietly reloading it, which surfaces to the user as
		// the underlying page appearing to reload and lose state. The dialog's own Save button
		// is unaffected by this restore — it calls this.frm.save(...) via closure (see
		// toolbar.js's set_page_actions), not cur_frm — so only the global Ctrl+S shortcut loses
		// the ability to target this dialog while it's open; use the visible Save button instead.
		this.previous_cur_frm = window.cur_frm;
		const route_key = frappe.get_route_str();
		const previous_page_entry = frappe.ui.pages[route_key];

		// initialize_new_doc() and refresh_header() call frappe.breadcrumbs.add()/update()
		// unconditionally (not gated by in_form/in_dialog). update() resolves the doc to
		// display from the BROWSER'S CURRENT ROUTE, not from this form — so whenever the
		// underlying page is itself a Form route (e.g. opening this dialog from Order
		// Receipt), it looks up a docname that doesn't match this dialog's phantom
		// document, gets undefined back, and throws. Because breadcrumbs.update() runs
		// inside render_form()'s run_serially chain, that throw aborts every later step,
		// including refresh_fields() — which is why only one field would render. Breadcrumb
		// display is meaningless for a modal anyway, so no-op both for the dialog's lifetime
		// and restore the real functions on teardown.
		this.previous_breadcrumbs_add = frappe.breadcrumbs.add;
		this.previous_breadcrumbs_update = frappe.breadcrumbs.update;
		frappe.breadcrumbs.add = () => {};
		frappe.breadcrumbs.update = () => {};

		this.form.refresh(this.seed_document.name);

		if (previous_page_entry) {
			frappe.ui.pages[route_key] = previous_page_entry;
		} else {
			delete frappe.ui.pages[route_key];
		}
		window.cur_frm = this.previous_cur_frm || null;
	}

	// Closes the dialog and fires the after_insert callback once the document saves.
	// cscript members are per-Form-instance handlers picked up by ScriptManager, so this
	// never affects regular full-page New Product forms.
	install_after_save_handler() {
		this.form.cscript.after_save = () => {
			const saved_document = this.form.doc;
			this.discard_confirmed = true;
			this.dialog.hide();
			if (this.after_insert) {
				this.after_insert(saved_document);
			}
		};
	}

	// Guards against losing unsaved changes. Bootstrap has already hidden the modal by the
	// time onhide fires, so the guard cannot cancel the hide — it re-shows the dialog and asks
	// for confirmation instead, hiding again only once the user approves the discard.
	handle_hide() {
		if (this.form && this.form.is_dirty() && !this.discard_confirmed) {
			this.dialog.show();
			frappe.confirm(__('Discard unsaved changes?'), () => {
				this.discard_confirmed = true;
				this.dialog.hide();
			});
			return;
		}
		this.teardown();
	}

	// Releases everything the embedded Form attached globally: the unsaved-changes
	// beforeunload listener, the cur_frm global, the breadcrumbs no-op patch, and the
	// dialog's DOM subtree. The cur_frm restore here is a backstop, not the primary fix —
	// Form.refresh() re-sets cur_frm to this.form every time it runs (including internally
	// after a successful save), so this catches whatever the most recent refresh left behind.
	teardown() {
		if (this.teardown_completed) {
			return;
		}
		this.teardown_completed = true;
		removeEventListener('beforeunload', this.form.beforeUnloadListener, { capture: true });
		if (window.cur_frm === this.form) {
			window.cur_frm = this.previous_cur_frm || null;
		}
		frappe.breadcrumbs.add = this.previous_breadcrumbs_add;
		frappe.breadcrumbs.update = this.previous_breadcrumbs_update;
		this.dialog.$wrapper.remove();
	}
}

// One-call entry point. options.seed_document must be a locals document
// (frappe.model.get_new_doc) when provided.
bullwheel.forms.open_form_dialog = function (doctype, options = {}) {
	const form_dialog = new FormDialog(doctype, options);
	form_dialog.open();
	return form_dialog;
};
