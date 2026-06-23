// Copyright (c) 2026 Barrie's Ski and Sports
// All Rights Reserved
// Unauthorized copying or distribution of this file is prohibited.

frappe.ui.form.on('Bulk Product Import', {
    refresh(frm) {
        frm.add_custom_button(__('Generate Import Sheet'), () => {
            if (frm.is_new()) {
                frappe.msgprint(__('Please save the document before generating the import sheet.'));
                return;
            }

            const url = '/api/method/bullwheel.ascend.doctype.bulk_product_import.bulk_product_import.generate_import_sheet'
                + '?name=' + encodeURIComponent(frm.doc.name);
            window.open(url);
        });
    }
});
