// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

frappe.provide('bullwheel.ascend');

// Utilized in function parameters to throw an error if parameter is not assigned at runtime.
function required(parameter_name) {
    throw new Error(`Missing required parameter "${parameter_name}"`);
}

// Words dropped when deriving an acronym from a vendor name, so they don't dilute it
// (e.g. "The North Face" -> "NF" is worse than "TNF"... but "Barrie's Ski and Sports, Inc." should skip "and"/"Inc").
const VENDOR_ACRONYM_STOPWORDS = new Set(['and', 'the', 'of', 'inc', 'llc', 'co', 'corp', 'company']);

// Suggest a short acronym from a vendor name: initials of each significant word, or the
// first three letters when the name is a single word. This is only ever a starting point —
// the user confirms/edits it before it is saved as an Order Receipt's vpn_prefix.
bullwheel.ascend.generate_vendor_acronym = function(vendor_name = required('vendor_name')) {
    const words = vendor_name
        .split(/[\s\-]+/)
        .map((word) => word.replace(/[^a-zA-Z]/g, ''))
        .filter((word) => word && !VENDOR_ACRONYM_STOPWORDS.has(word.toLowerCase()));

    if (!words.length) return '';
    if (words.length === 1) return words[0].slice(0, 3).toUpperCase();

    return words.map((word) => word[0].toUpperCase()).join('');
}

// Resolve a scanned identifier to one product ({doctype, name, description, upc}) and pass it to
// on_resolved — or null when nothing matches. When the scan matches several products equally well
// (a vendor part number shared across products, a duplicate UPC), the user picks one first; closing
// the picker without choosing calls nothing. See ascend/product_lookup.py:resolve_scanned_product.
bullwheel.ascend.resolve_scanned_product = function(identifier = required('identifier'), on_resolved = required('on_resolved')) {
    frappe.call({
        method: 'bullwheel.ascend.product_lookup.resolve_scanned_product',
        args: {identifier: identifier},
        callback(response) {
            const result = response.message || null;
            if (result && result.candidates) {
                bullwheel.ascend.pick_scanned_product(identifier, result.candidates, on_resolved);
                return;
            }
            on_resolved(result);
        }
    });
}

// Show one large button per candidate (sized for warehouse tablets) and pass the chosen product to
// on_chosen.
bullwheel.ascend.pick_scanned_product = function(identifier = required('identifier'), candidates = required('candidates'), on_chosen = required('on_chosen')) {
    const dialog = new frappe.ui.Dialog({
        title: __('Which product is {0}?', [frappe.utils.escape_html(identifier)]),
        fields: [{fieldtype: 'HTML', fieldname: 'candidates'}],
    });

    const $list = $('<div class="d-flex flex-column" style="gap: var(--margin-sm)"></div>');
    candidates.forEach((candidate) => {
        const details = [candidate.name, candidate.upc && __('UPC {0}', [candidate.upc])].filter(Boolean).join(' · ');
        $(`<button type="button" class="btn btn-default btn-lg text-left">
                <div class="bold">${frappe.utils.escape_html(candidate.description || candidate.name)}</div>
                <div class="text-muted small">${frappe.utils.escape_html(details)}</div>
            </button>`)
            .on('click', () => {
                dialog.hide();
                on_chosen(candidate);
            })
            .appendTo($list);
    });
    dialog.fields_dict.candidates.$wrapper.append($list);
    dialog.show();
}
