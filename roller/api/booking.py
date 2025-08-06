import frappe
from frappe import _
import json
from frappe.utils import now
from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
from roller.api.roller import get_new_access_token
from datetime import datetime
import requests
from collections import defaultdict
import uuid


@frappe.whitelist(allow_guest=True)
def handle_roller_webhook():
    ip_address = frappe.local.request_ip
    headers = dict(frappe.request.headers)
    body_raw = frappe.request.data
    try:
        body = json.loads(body_raw)
    except Exception:
        body = body_raw.decode("utf-8") if isinstance(body_raw, bytes) else str(body_raw)
    
    headers_str = json.dumps(headers, indent=4)
    body_str = json.dumps(body, indent=4) if isinstance(body, dict) else str(body)
    log_message = f"Roller Webhook Received\n\nIP Address:\n{ip_address}\n\nHeaders:\n{headers_str}\n\nBody:\n{body_str}"
    frappe.log_error(log_message, "Roller Webhook Log")

    
    try:
        # Check if the request has data
        if not frappe.request.data:
            print("No data received in request")
            frappe.local.response.http_status_code = 400
            return {"error": "No data received in request"}
        

        # -----Checking the authentication

        auth_header = frappe.get_request_header("X-Roller-Apikey")
        if not auth_header or ":" not in auth_header:
            print("Missing or invalid API key")
            frappe.local.response.http_status_code = 401
            return {"error": "Missing or invalid API key"}

        if auth_header.lower().startswith("token "):
            auth_header = auth_header[6:].strip()

        api_key, api_secret = auth_header.split(":", 1)

        # Find user with API key
        user = frappe.db.get_value("User", {"api_key": api_key})
        if not user:
            frappe.local.response.http_status_code = 401
            return {"error": "Invalid API key"}

        # Get hashed secret using get_doc + get_password
        user_doc = frappe.get_doc("User", user)
        stored_secret = user_doc.get_password("api_secret")

        if not stored_secret or not (api_secret == stored_secret):
            frappe.local.response.http_status_code = 401
            return {"error": "Invalid API secret"}

        # Set the authenticated user
        frappe.set_user(user)

        # -----Processing the webhook data
        
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
        settings = frappe.get_doc("Roller Settings")
        booking_doc = frappe.get_doc("Roller Booking", booking)
        if not booking_doc.response:
            frappe.log_error("Roller Webhook Error", "No response data found in Roller Booking.")
            return

        if booking_doc.sales_invoice:
            frappe.log_error("Roller Webhook Error", "Sales Invoice already exists for this booking.")
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
            frappe.log_error("Roller Webhook Error", _("Invoice for this booking is already created by a future update: {0}".format(
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
                    return_invoice.naming_series = settings.sales_return_naming_series or "ACC-SINV-RET-.YYYY.-"
                    
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
            default_customer = settings.default_customer
            customer = frappe.get_doc("Customer", default_customer)

        if not existing_invoice:
            inv = frappe.new_doc("Sales Invoice")
            inv.naming_series = settings.sales_invoice_naming_series or "ACC-SINV-.YYYY.-"
            inv.company = settings.default_company or frappe.get_single_value("Global Defaults", "default_company")
            inv.custom_roller_booking_reference = booking_reference
            inv.custom_roller_unique_id = uniqueId
        else:
            inv = frappe.get_doc("Sales Invoice", {"custom_roller_unique_id": uniqueId})
            if inv.docstatus == 1:
                frappe.log_error("Roller Webhook Error", "Cannot modify submitted invoice {0}".format(inv.name))
                frappe.db.set_value("Roller Booking", booking_doc.name, "message", _("Cannot modify submitted invoice {0}.").format(inv.name))
                return  # Do not modify submitted invoices
              
        # print(customer.name)
        # inv.name = invoice_name
        inv.set_posting_time = 1

        if inv.customer != customer.name:
            inv.customer = customer.name
            inv.title = customer.customer_name
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

        inv.taxes_and_charges = settings.default_sales_taxes_and_charges_template

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
                "mode_of_payment": settings.default_mode_of_payment or "Cash",  # Or a specific one
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

@frappe.whitelist()
def fetch_bookings_from_roller():
    settings = frappe.get_single("Roller Settings")

    start_date = settings.booking_start_date
    end_date = settings.booking_end_date
    
    if not start_date or not end_date:
        frappe.throw("Booking Start and End dates must be set in Roller Settings.")

    base_url = settings.playground_url if settings.environment == "Playground" else settings.live_url
    access_token = settings.access_token
    token_url = f"{base_url}/token"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    page_number = 1
    page_size = 500
    retried = False  # Flag to track if we've retried
    all_items = []

    frappe.logger().info("Started booking sync for dates: {} to {}".format(start_date, end_date))
    while True:
        params = {
            "pageNumber": page_number,
            "pageSize": page_size,
            "startDate": start_date,
            "endDate": end_date
        }
        #/data/bookingitems
        url = (
            f"{base_url}/data/bookingitems?"
            f"pageSize={page_size}&pageNumber={page_number}&"
            f"startDate={start_date}&endDate={end_date}"
        )
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 401 and not retried:
                print("Access token expired, trying to refresh...")
                # Try getting new token and retry once
                access_token = get_new_access_token(token_url, settings.client_id, settings.client_secret)
                if not access_token:
                    frappe.throw("Failed to refresh access token.")
                # Save new token in settings
                settings.access_token = access_token
                frappe.db.set_single_value("Roller Settings", "access_token", access_token)
                # settings.save(ignore_permissions=True)

                retried = True
                continue  # Retry the same request with new token

            elif response.status_code == 401 and retried:
                frappe.throw("Unauthorized (401) even after refreshing access token.")

            # Handle any non-successful response
            if not response.ok:
                try:
                    message = response.json().get("message", response.text)
                except Exception:
                    message = response.text
                frappe.log_error("Roller Webhook Error", f"Roller API Error: {message}")
                frappe.throw(_("Roller API Error: {0}").format(message))    


            response.raise_for_status()

            data = response.json()
            print(data)
            items = data.get("items", [])
            all_items.extend(items)

            if data.get("currentPage", 1) >= data.get("totalPages", 1):
                break
            page_number += 1
        
        except requests.exceptions.RequestException as e:
            frappe.log_error(frappe.get_traceback(), "Roller Fetch Bookings Error")
            frappe.throw(f"Failed to fetch bookings from Roller API: {e}")

    # Group items by bookingReference
    grouped = defaultdict(list)
    for item in all_items:
        grouped[item["bookingReference"]].append(item)

    print(f"Total bookings fetched: {len(all_items)}")
    for booking_reference, items in grouped.items():
        if frappe.db.exists("Roller Booking", {"booking_reference": booking_reference}):
            continue

        frappe.logger().info("Processing booking reference: {}".format(booking_reference))
        first = items[0]
        booking = {
            "amountOwing": 0.0,
            "bookingReference": booking_reference,
            "channel": first.get("bookingLocation", "POS"),
            "comments": first.get("bookingNotes", ""),
            "createdDate": first["createdDate"],
            "deviceId": 0,
            "discount": float(first.get("discountAmount", 0.0)),
            "fees": float(first.get("bookingFeeAmount", 0.0)),
            "items": [],
            "name": first.get("bookingName", ""),
            "posNotes": first.get("bookingPosNotes", ""),
            "remainder": 0.0,
            "source": "POS",
            "status": first.get("bookingStatus", "PendingPayment"),
            "total": float(first.get("bookingTotal", 0.0)),
            "uniqueId": first["bookingUniqueId"]
        }

        # Add customerId only if it exists
        if first.get("bookingCustomerId"):
            booking["customerId"] = int(first["bookingCustomerId"])

        booking_json = {
            "data": {
                "booking": booking
            },
            "eventDate": first["createdDate"],
            "eventType": 1,
            "id": str(uuid.uuid4()),
            "sendDate": first["createdDate"],
            "type": 1
        }


        for item in items:
            booking_json["data"]["booking"]["items"].append({
                "bookingDate": item["bookingDate"],
                "bookingEndDate": item["bookingEndDate"],
                "bookingItemId": int(item["bookingItemId"]),
                "cost": float(item.get("cost", 0.0)),
                "createdDate": item["createdDate"],
                "discount": float(item.get("discountAmount", 0.0)),
                "groupSize": item.get("groupSize", 1),
                "modifiers": item.get("modifiers", []),
                "productId": int(item["productId"]),
                "quantity": item.get("quantity", 1)
            })

        # Create and save the Roller Booking doc
        doc = frappe.new_doc("Roller Booking")
        doc.booking_reference = booking_reference
        doc.response = frappe.as_json(booking_json)
        doc.insert(ignore_permissions=True)
        make_invoice_from_roller_booking(doc.name)
        # frappe.db.commit()

    frappe.logger().info("Bookings sync completed from {} to {}.".format(start_date, end_date))
    return "Bookings sync completed for given dates."
        

# Helper: Create/Get Customer
def get_or_create_customer(customer_id, name):
    customer = frappe.db.get_value("Customer", {"custom_roller_customer_id": customer_id})
    if customer:
        return frappe.get_doc("Customer", customer)
    
    doc = frappe.new_doc("Customer")
    doc.customer_name = name or f"Roller Customer {customer_id}"
    doc.customer_type = "Individual"
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
