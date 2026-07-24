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