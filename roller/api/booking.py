import frappe
from frappe import _
import json
from frappe.model.document import Document
from frappe.utils import now
from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
from datetime import datetime

@frappe.whitelist(allow_guest=True)
def handle_roller_webhook():
    try:
        frappe.set_user("Administrator")
        data = json.loads(frappe.request.data)
        booking_data = data.get("data", {}).get("booking", {})
        
        booking = frappe.new_doc("Roller Booking")
        booking.booking_reference = booking_data.get("bookingReference")
        booking.response = frappe.as_json(data)
        booking.save(ignore_permissions=True)
        make_invoice_from_roller_booking(booking.name)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Roller Webhook Error")

@frappe.whitelist()
def make_invoice_from_roller_booking(booking):
    try:
        frappe.set_user("Administrator")
        booking_doc = frappe.get_doc("Roller Booking", booking)
        if not booking_doc.response:
            frappe.log_error(frappe.get_traceback(), "No response data found in Roller Booking.")
            return

        if booking_doc.sales_invoice:
            frappe.log_error(frappe.get_traceback(), "Sales Invoice already exists for this booking.")
            return
            
        # Check for duplicate booking_reference in future with invoice already created
        future_duplicates = frappe.get_all(
            "Roller Booking",
            filters={
                "booking_reference": booking_doc.booking_reference,
                "creation": [">", booking_doc.creation],
                "sales_invoice": ["!=", ""]
            },
            fields=["name", "creation", "sales_invoice"]
        )

        if future_duplicates:
            frappe.log_error(frappe.get_traceback(), _("Invoice for this booking is already created by a future update: {0}".format(
                future_duplicates[0].name
            )))
            frappe.db.set_value("Roller Booking", booking_doc.name, "message", _("Invoice for this booking is already created by a future update: {0}".format(
                future_duplicates[0].name
            )))
            return "Invoice for this booking is already created by a future update: {0}".format(
                future_duplicates[0].name
            )
            
        data = json.loads(booking_doc.response)
        event_type = data.get("eventType")
        booking = data.get("data", {}).get("booking", {})
        booking_reference = booking.get("bookingReference")
        uniqueId = booking.get("uniqueId")
        customer_id = booking.get("customerId")
        status = booking.get("status")
        
        # Check if invoice exists
        existing_invoice = frappe.db.exists("Sales Invoice", {"custom_roller_unique_id": uniqueId})

        # Cancel event
        if event_type == 3:
            if existing_invoice:
                inv = frappe.get_doc("Sales Invoice", {"custom_roller_unique_id": uniqueId})
                if inv.docstatus == 1:
                    return_invoice = make_sales_return(inv.name)
                    for item in return_invoice.items:
                        item.qty = -abs(item.qty)  # Ensure it's negative
                    # return_invoice.is_return = 1
                    # return_invoice.return_against = inv.name
                    return_invoice.naming_series = "ACC-SINV-RET-.YYYY.-"
                    
                    print(str(return_invoice.return_against))
                    print(str(inv.posting_date), str(inv.posting_time))
                    print(str(return_invoice.posting_date), str(return_invoice.posting_time))
                    return_invoice.save(ignore_permissions=True)
                    return_invoice.submit()

                    frappe.db.set_value("Roller Booking", booking_doc.name, "sales_invoice", return_invoice.name)
                    frappe.db.set_value("Roller Booking", booking_doc.name, "message", _("Sales Invoice (Return) {0} created successfully.").format(return_invoice.name))
            return

        if status == "Cancelled":
            return

        # Create or Update
        if customer_id:
            customer = get_or_create_customer(customer_id, booking.get("name"))
        else:
            default_customer = frappe.db.get_single_value("Roller Settings", "default_customer")
            customer = frappe.get_doc("Customer", default_customer)

        if not existing_invoice:
            inv = frappe.new_doc("Sales Invoice")
            inv.naming_series = "ACC-SINV-.MM.-.YY.-"
            inv.custom_roller_booking_reference = booking_reference
            inv.custom_roller_unique_id = uniqueId
        else:
            inv = frappe.get_doc("Sales Invoice", {"custom_roller_unique_id": uniqueId})
            if inv.docstatus == 1:
                frappe.log_error(frappe.get_traceback(), "Roller Webhook Error Cannot change submitted invoice")
                return  # Do not modify submitted invoices
              
        # print(customer.name)
        # inv.name = invoice_name
        inv.set_posting_time = 1

        if inv.customer != customer.name:
            inv.customer = customer.name
            inv.title = customer.name
            inv.contact_person = ""
            inv.contact_display = ""

        # inv.due_date = now()
        # inv.posting_date = now()

        earliest_date = None
        latest_date = None

        # Add items
        inv.items = []
        for item in booking.get("items", []):
            product = get_or_create_item(item)

            # Parse bookingDate
            item_booking_date_str = item.get("bookingDate")
            if item_booking_date_str:
                item_booking_date = datetime.strptime(item_booking_date_str, "%Y-%m-%d")
                if not earliest_date or item_booking_date < earliest_date:
                    earliest_date = item_booking_date
                if not latest_date or item_booking_date > latest_date:
                    latest_date = item_booking_date
                    
            base_rate = float(item.get("cost") or 0)

            # Add modifier amounts
            modifiers = item.get("modifiers", [])
            modifier_total = sum(
                float(mod.get("amount") or 0) * float(mod.get("quantity") or 1)
                for mod in modifiers
            )

            rate = base_rate + modifier_total
            qty = float(item.get("quantity") or 1)

            inv.append("items", {
                "item_code": product.name,
                "item_name": product.item_name,
                "qty": qty,
                "rate": rate,
                "price_list_rate": rate,
            })

            # print("Cost:", item.get("cost"))
            # print("Discount:", item.get("discount", 0))
            # print("Rate:", item.get("cost") - item.get("discount", 0))

        # Set posting_date and due_date based on bookingDates
        inv.posting_date = earliest_date.date() if earliest_date else now()
        if inv.due_date != latest_date.date() if latest_date else now():
            # Only set due_date if it is different from posting_date
            inv.due_date = latest_date.date() if latest_date else now()
            inv.set("payment_schedule", [])

        
        if inv.remarks != booking.get("comments"):
            inv.remarks = booking.get("comments")

        if inv.discount_amount != float(booking.get("discount") or 0):
            inv.apply_discount_on = "Grand Total"
            inv.discount_amount = float(booking.get("discount") or 0)

        inv.taxes_and_charges = frappe.db.get_single_value("Roller Settings", "default_sales_taxes_and_charges_template")

        inv.set_taxes()

        inv.set_missing_values()

        # Mark as paid
        # if status == "Paid":
        #     inv.is_pos = 1
        #     inv.set("payments", [{
        #         "mode_of_payment": frappe.db.get_single_value("Roller Settings", "default_mode_of_payment") or "Cash",  # Or a specific one
        #         "amount": float(booking.get("total") or 0)
        #     }])
        #     inv.set_paid_amount()

        
        if status == "Paid" or status == "PartiallyPaid":
            inv.is_pos = 1
            inv.set("payments", [{
                "mode_of_payment": frappe.db.get_single_value("Roller Settings", "default_mode_of_payment") or "Cash",
                "amount": float(float(booking.get("total") or 0) - float(booking.get("remainder") or 0))
            }])
            inv.set_paid_amount()

        
        if status == "Paid":
            inv.set_posting_time = 0
            inv.posting_date = now()
            inv.due_date = now()
            inv.set("payment_schedule", [])
            inv.save(ignore_permissions=True)
            inv.submit()
        else:
            inv.save(ignore_permissions=True)

        frappe.db.set_value("Roller Booking", booking_doc.name, "sales_invoice", inv.name)
        frappe.db.set_value("Roller Booking", booking_doc.name, "message", _("Sales Invoice {0} created successfully.").format(inv.name))


    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Roller Webhook Error")
        # return {"status": "error", "message": str(e)}

# Helper: Create/Get Customer
def get_or_create_customer(customer_id, name):
    customer = frappe.db.get_value("Customer", {"custom_roller_customer_id": customer_id})
    if customer:
        return frappe.get_doc("Customer", customer)
    
    doc = frappe.new_doc("Customer")
    doc.customer_name = name or f"Roller Customer {customer_id}"
    doc.customer_group = "All Customer Groups"
    doc.territory = "All Territories"
    doc.custom_roller_customer_id = customer_id
    doc.save(ignore_permissions=True)
    return doc

# Helper: Create/Get Item
def get_or_create_item(item_data):
    product_id = item_data.get("productId")
    item = frappe.db.get_value("Item", {"custom_roller_product_id": product_id})
    if item:
        return frappe.get_doc("Item", item)

    doc = frappe.new_doc("Item")
    doc.item_code = f"ROLLER-{product_id}"
    doc.item_name = item_data.get("productId")
    doc.item_group = "All Item Groups"  # Ensure exists
    doc.stock_uom = "Nos"
    doc.is_stock_item = 0
    doc.custom_roller_product_id = product_id
    doc.save(ignore_permissions=True)
    return doc
