// Copyright (c) 2025, Sowaan and contributors
// For license information, please see license.txt

frappe.ui.form.on("Roller Booking", {
	refresh(frm) {
        if (!frm.doc.sales_invoice && !frm.is_new()) {
            const btn = frm.add_custom_button('<i class="fa fa-plus"></i> Create Sales Invoice', () => {
                frappe.call({
                    method: "roller.api.booking.make_invoice_from_roller_booking",
                    args: { booking: frm.doc.name },
                    freeze: true,
                    callback(r) {
                        if (!r.exc) {
                            frappe.msgprint(r.message);
                            frm.reload_doc();
                        }
                    }
                });
            });
            // Optional: make it red or blue
            if (btn) {
                $(btn).addClass('btn-primary'); // or 'btn-primary'
            }
        }
        if (frm.doc.sales_invoice && !frm.is_new()) {
            const btn = frm.add_custom_button(
                '<i class="fa fa-unlink"></i> Unlink Sales Invoice',
                () => {
                    frappe.confirm(
                        'Are you sure you want to unlink the Sales Invoice?',
                        () => {
                            frm.set_value('sales_invoice', null);
                            frm.save().then(() => {
                                frappe.msgprint('Sales Invoice unlinked successfully.');
                            });
                        }
                    );
                }
            );

            // Optional: make it red or blue
            if (btn) {
                $(btn).addClass('btn-danger'); // or 'btn-primary'
            }
        }
    }
});
