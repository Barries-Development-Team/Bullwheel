// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

frappe.provide('bullwheel.ascend');

// Utilized in function parameters to throw an error if parameter is not assigned at runtime.
function required(parameter_name) {
    throw new Error(`bullwheel.ascend.generate_vpn: missing required parameter "${parameter_name}"`);
}

// Normalize one VPN component: strip anything that isn't alphanumeric or whitespace, collapse
// remaining whitespace to a single "-", then uppercase. Non-alphanumeric characters are
// stripped before whitespace is turned into "-" so the separator itself survives the strip.
function format_vpn_component(value) {
    return String(value)
        .trim()
        .replace(/[^a-zA-Z0-9\s]/g, '')
        .replace(/\s+/g, '-')
        .toUpperCase();
}

// Ascend's Part Number column is limited to 50 characters; 45 is used as the effective limit
// to leave a margin of safety.
const PART_NUMBER_LIMIT = 45;

// Async: appending the Counter component requires checking Ascend for an existing VendorProducts
// row with that exact part number, one candidate at a time, via vendor_product_match_count.
bullwheel.ascend.generate_vpn = async function({
    vendor_id = required('vendor_id'),
    vpn_prefix = required('vpn_prefix'),
    brand = required('brand'),
    model = required('model'),
    size,
    color
} = {}) {
    // VPN Components
    // Vendor Acronym-Brand-Model-Size-Color-Counter

    // Brand alone can run long (e.g. "The North Face Inc."); cap it to its first two words
    // up front so it doesn't dominate the character budget.
    const limited_brand = brand.trim().split(/\s+/).slice(0, 2).join(' ');

    const build_base_vpn = (model_value) => [vpn_prefix, limited_brand, model_value, size, color]
        .filter((value) => value != null && String(value).trim() !== '')
        .map(format_vpn_component)
        .join('-');

    let base_vpn = build_base_vpn(model);

    // Still over the limit: shorten "model" by exactly the overage rather than a fixed amount,
    // so short overages cost as little of "model" as possible.
    if (base_vpn.length > PART_NUMBER_LIMIT) {
        const overage = base_vpn.length - PART_NUMBER_LIMIT;
        const formatted_model = format_vpn_component(model);
        const truncated_model = formatted_model.slice(0, Math.max(0, formatted_model.length - overage));
        base_vpn = build_base_vpn(truncated_model);
    }

    if (base_vpn.length > PART_NUMBER_LIMIT) {
        throw new Error(`bullwheel.ascend.generate_vpn: generated VPN "${base_vpn}" exceeds the ${PART_NUMBER_LIMIT}-character limit even after truncating "model".`);
    }

    for (let counter = 1; ; counter++) {
        const candidate_vpn = `${base_vpn}-${counter}`;

        const response = await frappe.call('bullwheel.ascend.doctype.vendor_product.vendor_product.vendor_product_match_count', {
            vendor_id: vendor_id,
            part_number: candidate_vpn,
            part_number_similarity: 'equals'
        });

        if (!response.message) return candidate_vpn;
    }
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