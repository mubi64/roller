import frappe

def set_customer_naming_series():
    try:
        selling_settings = frappe.get_single("Selling Settings")
        selling_settings.cust_master_name = "Naming Series"
        selling_settings.save()
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Failed to set Selling Settings")