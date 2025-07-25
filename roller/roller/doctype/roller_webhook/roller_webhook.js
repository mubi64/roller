// Copyright (c) 2025, Sowaan and contributors
// For license information, please see license.txt

frappe.ui.form.on('Roller Webhook', {
    create_in_roller(frm) {
        frappe.call({
            method: "roller.api.webhook.create_roller_webhook",
            args: { docname: frm.doc.name },
            freeze: true,
            callback(r) {
                if (!r.exc) {
                    frappe.msgprint("Webhook created successfully.");
                    frm.reload_doc();
                }
            }
        });
    },
    delete_from_roller(frm) {
        frappe.confirm("Are you sure you want to delete this webhook?", () => {
            frappe.call({
                method: "roller.api.webhook.delete_roller_webhook",
                args: { docname: frm.doc.name },
                freeze: true,
                callback(r) {
                    if (!r.exc) {
                        frappe.msgprint("Webhook deleted.");
                        frm.reload_doc();
                    }
                }
            });
        });
    }
});

