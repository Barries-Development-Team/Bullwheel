// Copyright (c) 2026 Barrie's Ski and Sports
// All Rights Reserved
// Unauthorized copying or distribution of this file is prohibited.

frappe.ui.form.on('Bulk Product Import', {
    refresh(frm) {
        if (frm.is_new() || frm.doc.status === 'Exported') {
            return;
        }

        frm.add_custom_button(__('Get Pending Products'), () => {
            frappe.call({
                method: 'bullwheel.ascend.doctype.bulk_product_import.bulk_product_import.get_pending_products',
                args: { vendor: frm.doc.vendor },
                callback(response) {
                    const already_added = new Set((frm.doc.new_products || []).map((row) => row.new_product));
                    (response.message || [])
                        .filter((name) => !already_added.has(name))
                        .forEach((name) => frm.add_child('new_products', { new_product: name }));
                    frm.refresh_field('new_products');
                    frm.dirty();
                    if (!(response.message || []).length) {
                        frappe.show_alert({ message: __('No Pending New Products for this vendor.'), indicator: 'orange' });
                    }
                },
            });
        });

        frm.add_custom_button(__('Generate Import Sheet'), () => {
            if (frm.is_dirty()) {
                frappe.msgprint(__('Please save the document before generating the import sheet.'));
                return;
            }

            frappe.confirm(
                __('Generating the sheet marks every product in this batch as Exported. In Ascend, choose {0} while importing it (File > Import > Vendor Products). Continue?', [frm.doc.vendor]),
                () => {
                    window.open('/api/method/bullwheel.ascend.doctype.bulk_product_import.bulk_product_import.generate_import_sheet'
                        + '?name=' + encodeURIComponent(frm.doc.name));
                    setTimeout(() => frm.reload_doc(), 2000);
                }
            );
        });
    }
});
