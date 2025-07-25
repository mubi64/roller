// Copyright (c) 2025, Sowaan and contributors
// For license information, please see license.txt

frappe.ui.form.on('Roller Settings', {
    get_access_token: function (frm) {
        frappe.call({
            method: 'roller.api.roller.get_access_token',
            args: {
                environment: frm.doc.environment,
                client_id: frm.doc.client_id,
                client_secret: frm.doc.client_secret,
                playground_url: frm.doc.playground_url,
                live_url: frm.doc.live_url
            },
            callback: function (r) {
                if (r.message) {
                    frm.set_value('access_token', r.message);
                    frm.save();
                    frappe.show_alert({ message: 'Access Token fetched successfully!', indicator: 'green' });
                }
            },
            freeze: true,
            freeze_message: 'Fetching Access Token...'
        });
    },
    fetch_customers: function (frm) {
        frappe.call({
            method: 'roller.api.customer.fetch_customers_from_roller',
            callback: function (r) {
                if (r.message) {
                    frappe.msgprint(__(r.message));
                }
            },
            freeze: true,
            freeze_message: 'Fetching customers from Roller API...'
        });
    },
    fetch_products: function(frm) {
        frappe.call({
            method: 'roller.api.product.fetch_products_from_roller',
            callback: function(r) {
                if (r.message) {
                    frappe.msgprint(__(r.message));
                }
            },
            freeze: true,
            freeze_message: 'Fetching products from Roller API...'
        });
    }
});

