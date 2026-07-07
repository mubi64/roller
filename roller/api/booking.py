import json
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

import frappe
import requests
from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
from frappe import _
from frappe.utils import flt, now

from roller.api.roller import get_new_access_token


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

# Roller booking statuses that mean the whole booking was cancelled / fully refunded.
CANCELLED_STATUSES = {"Cancelled", "Refunded"}
AMOUNT_TOLERANCE = 0.01


def _set_booking_msg(booking_name, message):
    frappe.db.set_value("Roller Booking", booking_name, "message", message)


def _link_booking(booking_name, invoice_name, message=None):
    """Link a Roller Booking to its Sales Invoice (and optionally set a message)."""
    frappe.db.set_value("Roller Booking", booking_name, "sales_invoice", invoice_name)
    if message:
        _set_booking_msg(booking_name, message)


def _get_original_invoice(unique_id=None, booking_reference=None):
    """Find the original Roller invoice, never one of its returns."""
    filters = {"is_return": 0}
    if unique_id:
        filters["custom_roller_unique_id"] = unique_id
        invoice = frappe.db.exists("Sales Invoice", filters)
        if invoice:
            return invoice

    if booking_reference:
        filters = {
            "is_return": 0,
            "custom_roller_booking_reference": booking_reference,
        }
        return frappe.db.exists("Sales Invoice", filters)


def _parse_booking_response(response):
    if not response:
        return {}, {}

    try:
        data = json.loads(response) if isinstance(response, str) else response
    except (TypeError, ValueError):
        return {}, {}

    return data, data.get("data", {}).get("booking", {})


def _get_previous_booking(booking_doc):
    """Return the most recent earlier Roller snapshot for this booking reference."""
    previous = frappe.get_all(
        "Roller Booking",
        filters={
            "booking_reference": booking_doc.booking_reference,
            "creation": ["<", booking_doc.creation],
        },
        fields=["name", "response"],
        order_by="creation desc",
        limit=1,
    )
    if not previous:
        return None, {}

    _, booking = _parse_booking_response(previous[0].response)
    return previous[0].name, booking


def _booking_items_by_id(items):
    return {
        str(item.get("bookingItemId")): item
        for item in (items or [])
        if item.get("bookingItemId") is not None
    }


def _removed_booking_items(previous_booking, latest_booking):
    previous_items = _booking_items_by_id(previous_booking.get("items"))
    latest_ids = set(_booking_items_by_id(latest_booking.get("items")))
    return [item for item_id, item in previous_items.items() if item_id not in latest_ids]


def _booking_total(booking):
    total = booking.get("total")
    return flt(total) if total is not None else None


def _event_id_from_response(response):
    data, _ = _parse_booking_response(response)
    return str(data.get("id") or "")


def _find_credit_note_for_event(booking_doc, original_invoice):
    """Find a credit note already linked to an earlier copy of this Roller event."""
    event_id = _event_id_from_response(booking_doc.response)
    if not event_id:
        return None

    earlier_logs = frappe.get_all(
        "Roller Booking",
        filters={
            "booking_reference": booking_doc.booking_reference,
            "creation": ["<", booking_doc.creation],
            "sales_invoice": ["!=", ""],
        },
        fields=["sales_invoice", "response"],
        order_by="creation desc",
    )
    for log in earlier_logs:
        if _event_id_from_response(log.response) != event_id:
            continue
        if frappe.db.exists(
            "Sales Invoice",
            {
                "name": log.sales_invoice,
                "is_return": 1,
                "return_against": original_invoice,
                "docstatus": ["<", 2],
            },
        ):
            return log.sales_invoice


def _handle_full_cancellation(
    booking_doc, settings, invoice_name, booking=None, previous_booking=None
):
    """Reverse an invoiced booking that Roller has fully cancelled / refunded.

    - No invoice yet         -> nothing to reverse (booking was never invoiced).
    - Draft invoice (unpaid) -> delete it; nothing was ever finalised.
    - Already cancelled       -> leave it; just record the message.
    - Submitted invoice       -> create a submitted Sales Return (credit note), once.
    """
    booking_name = booking_doc.name
    if not invoice_name:
        _set_booking_msg(booking_name, _("Booking cancelled, but no invoice exists to reverse."))
        return

    inv = frappe.get_doc("Sales Invoice", invoice_name)

    if inv.docstatus == 0:  # draft / unpaid -> nothing was finalised, just remove it
        frappe.delete_doc("Sales Invoice", inv.name, ignore_permissions=True, force=True)
        _set_booking_msg(booking_name, _("Booking cancelled; draft invoice {0} deleted.").format(invoice_name))
        return

    if inv.docstatus == 2:  # already cancelled
        _set_booking_msg(booking_name, _("Booking cancelled; invoice {0} was already cancelled.").format(invoice_name))
        return

    # Use the same outstanding-total logic as a partial refund. This correctly returns
    # only the balance if the booking was partially refunded before full cancellation.
    cancelled_booking = dict(booking or {})
    cancelled_booking["total"] = 0
    cancelled_booking["items"] = []
    return _handle_partial_refund(
        booking_doc,
        settings,
        inv,
        cancelled_booking,
        previous_booking=previous_booking,
    )


def _roller_item_qty_map(items):
    """Aggregate a Roller booking payload's items into {item_code: total_qty}.

    The invoice line's item_code is whatever get_or_create_item resolved the productId to:
    an existing Item matched by custom_roller_product_id (which can be any code, e.g.
    "1850040"), or a freshly created "ROLLER-{productId}". We resolve the same way here so
    the keys line up with the invoice lines — assuming the "ROLLER-" prefix would silently
    miss pre-existing items and credit back the wrong quantity.
    """
    qty_map = defaultdict(float)
    for it in items or []:
        product_id = it.get("productId")
        item_code = frappe.db.get_value("Item", {"custom_roller_product_id": product_id}, "name")
        qty_map[item_code or f"ROLLER-{product_id}"] += float(it.get("quantity") or 1)
    return qty_map


def _fit_return_to_refund_amount(return_invoice, refund_amount):
    """Keep the selected return items but make their calculated total match Roller."""
    return_invoice.run_method("calculate_taxes_and_totals")
    calculated = abs(flt(return_invoice.grand_total))
    if abs(calculated - refund_amount) <= AMOUNT_TOLERANCE:
        return

    # make_sales_return copies the full source invoice discount. That is unsuitable after
    # trimming to a subset of lines, so use the Roller total difference as the authority.
    return_invoice.apply_discount_on = ""
    return_invoice.discount_amount = 0
    return_invoice.additional_discount_percentage = 0
    return_invoice.run_method("calculate_taxes_and_totals")

    calculated = abs(flt(return_invoice.grand_total))
    if not calculated:
        return

    factor = refund_amount / calculated
    for line in return_invoice.items:
        line.rate = flt(line.rate) * factor
        line.price_list_rate = line.rate
        line.discount_percentage = 0
        line.discount_amount = 0
    return_invoice.run_method("calculate_taxes_and_totals")


def _handle_partial_refund(
    booking_doc, settings, inv, booking, previous_booking=None, record_noop=True
):
    """Create only the still-outstanding credit for a reduced Roller booking total."""
    # Serialize refund processing for this invoice so two simultaneous webhook retries
    # cannot both calculate the same outstanding refund before either one commits.
    frappe.db.get_value("Sales Invoice", inv.name, "name", for_update=True)

    duplicate_return = _find_credit_note_for_event(booking_doc, inv.name)
    if duplicate_return:
        _link_booking(
            booking_doc.name,
            duplicate_return,
            _("Credit Note {0} already exists for this Roller event.").format(
                duplicate_return
            ),
        )
        return duplicate_return

    prior_returns = frappe.get_all(
        "Sales Invoice",
        filters={"return_against": inv.name, "docstatus": ["<", 2]},
        fields=["name", "docstatus", "grand_total"],
    )
    draft_return = next((row.name for row in prior_returns if row.docstatus == 0), None)
    if draft_return:
        _link_booking(
            booking_doc.name,
            draft_return,
            _("Draft Credit Note {0} already exists for invoice {1}.").format(
                draft_return, inv.name
            ),
        )
        return draft_return

    latest_total = _booking_total(booking)
    if latest_total is None:
        _link_booking(
            booking_doc.name,
            inv.name,
            _("Latest Roller booking total is missing; no Credit Note was created."),
        )
        return

    credited_total = sum(abs(flt(row.grand_total)) for row in prior_returns)
    current_invoiced_total = max(flt(inv.grand_total) - credited_total, 0)
    refund_amount = current_invoiced_total - latest_total

    if abs(refund_amount) <= AMOUNT_TOLERANCE:
        if record_noop:
            _link_booking(
                booking_doc.name,
                inv.name,
                _(
                    "No total change for Sales Invoice {0}; payment/status update only."
                ).format(inv.name),
            )
        return

    if refund_amount < 0:
        _link_booking(
            booking_doc.name,
            inv.name,
            _(
                "Roller total increased by {0}; an additional invoice or adjustment is needed."
            ).format(frappe.format_value(abs(refund_amount), {"fieldtype": "Currency"})),
        )
        return

    removed_items = _removed_booking_items(previous_booking or {}, booking)

    # Original invoiced qty per item (the submitted invoice is never modified).
    original_qty = defaultdict(float)
    for line in inv.items:
        original_qty[line.item_code] += float(line.qty)

    new_qty = _roller_item_qty_map(booking.get("items", []))

    # Qty already credited back across any prior returns for this invoice.
    already_returned = defaultdict(float)
    for prior_return in prior_returns:
        for line in frappe.get_doc("Sales Invoice", prior_return.name).items:
            already_returned[line.item_code] += abs(float(line.qty))

    to_return = {}
    for item_code, orig in original_qty.items():
        delta = (orig - new_qty.get(item_code, 0)) - already_returned.get(item_code, 0)
        if delta > 0:
            to_return[item_code] = delta

    if removed_items:
        removed_codes = set(_roller_item_qty_map(removed_items))
        detected_return = {
            item_code: qty
            for item_code, qty in to_return.items()
            if item_code in removed_codes
        }
        if detected_return:
            to_return = detected_return

    if not to_return:
        _link_booking(
            booking_doc.name,
            inv.name,
            _(
                "Roller total is lower by {0}, but no refundable item reduction was detected."
            ).format(frappe.format_value(refund_amount, {"fieldtype": "Currency"})),
        )
        return

    return_invoice = make_sales_return(inv.name)

    # make_sales_return negates the full original quantities; trim each line down to the
    # outstanding decrease and drop lines that aren't being refunded.
    remaining = dict(to_return)
    kept_lines = []
    for line in return_invoice.items:
        want = remaining.get(line.item_code, 0)
        if want <= 0:
            continue
        take = min(want, abs(float(line.qty)))
        line.qty = -take
        remaining[line.item_code] = want - take
        kept_lines.append(line)
    return_invoice.set("items", kept_lines)

    return_invoice.naming_series = settings.sales_return_naming_series or "ACC-SINV-RET-.YYYY.-"
    # Same constraint as a full return: anchor to the original invoice's posting datetime
    # so ERPNext never rejects the return for being dated before its source invoice.
    return_invoice.set_posting_time = 1
    return_invoice.posting_date = inv.posting_date
    return_invoice.posting_time = inv.posting_time
    _fit_return_to_refund_amount(return_invoice, refund_amount)

    # POS invoices carry a payment equal to the grand total; make_sales_return copies the
    # full negative payment, so replace it before the partial credit note is first saved.
    if return_invoice.is_pos and return_invoice.get("payments"):
        mode = (
            return_invoice.payments[0].mode_of_payment
            or settings.default_mode_of_payment
            or "Cash"
        )
        return_invoice.set(
            "payments",
            [{"mode_of_payment": mode, "amount": return_invoice.grand_total}],
        )
        return_invoice.set_paid_amount()

    return_invoice.save(ignore_permissions=True)

    created_refund_amount = abs(flt(return_invoice.grand_total))
    if abs(created_refund_amount - refund_amount) > AMOUNT_TOLERANCE:
        frappe.delete_doc(
            "Sales Invoice", return_invoice.name, ignore_permissions=True, force=True
        )
        _link_booking(
            booking_doc.name,
            inv.name,
            _(
                "Refund detected ({0}), but item return totals {1}; Credit Note was not created."
            ).format(
                frappe.format_value(refund_amount, {"fieldtype": "Currency"}),
                frappe.format_value(created_refund_amount, {"fieldtype": "Currency"}),
            ),
        )
        frappe.log_error(
            title="Roller Partial Refund Amount Mismatch",
            message=(
                "Booking {0}, invoice {1}: expected refund {2}, item return {3}, "
                "removed booking item ids {4}"
            ).format(
                booking_doc.booking_reference,
                inv.name,
                refund_amount,
                created_refund_amount,
                [item.get("bookingItemId") for item in removed_items],
            ),
        )
        return

    return_invoice.submit()

    frappe.db.set_value("Roller Booking", booking_doc.name, "sales_invoice", return_invoice.name)
    _set_booking_msg(
        booking_doc.name,
        _("Credit Note {0} created for {1}, refund amount {2}.").format(
            return_invoice.name,
            inv.name,
            frappe.format_value(refund_amount, {"fieldtype": "Currency"}),
        ),
    )
    return return_invoice.name


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
        
        # Check if invoice exists (the original, never a credit note created for it).
        existing_invoice = _get_original_invoice(uniqueId, booking_reference)

        # Full cancellation / refund: Roller signals this via eventType 3 (webhook) or a
        # cancelled booking status (which is also how it arrives through Fetch Bookings).
        _prev_name, previous_booking = _get_previous_booking(booking_doc)

        if event_type == 3 or status in CANCELLED_STATUSES:
            _handle_full_cancellation(
                booking_doc,
                settings,
                existing_invoice,
                booking=booking,
                previous_booking=previous_booking,
            )
            return

        if existing_invoice:
            inv = frappe.get_doc("Sales Invoice", existing_invoice)
            if inv.docstatus == 1:
                _handle_partial_refund(
                    booking_doc,
                    settings,
                    inv,
                    booking,
                    previous_booking=previous_booking,
                )
                return  # Submitted invoices are not modified

        # Create or Update
        if customer_id:
            customer = get_or_create_customer(customer_id, booking.get("name"), settings.default_address, booking.get("customerEmail") or booking.get("email"))
        else:
            default_customer = settings.default_customer
            customer = frappe.get_doc("Customer", default_customer)

        # Customer Address
        existing_address = frappe.db.exists(
            "Dynamic Link",
            {
                "link_doctype": "Customer",
                "link_name": customer.name,
                "parenttype": "Address"
            }
        )

        if not existing_address:
            for attempt in range(3):
                try:
                    address_doc = frappe.get_doc("Address", settings.default_address)
                    already_linked = any(
                        l.link_doctype == "Customer" and l.link_name == customer.name
                        for l in address_doc.get("links", [])
                    )
                    if not already_linked:
                        address_doc.append("links", {
                            "link_doctype": "Customer",
                            "link_name": customer.name
                        })
                        address_doc.save(ignore_permissions=True)
                    break
                except frappe.exceptions.TimestampMismatchError:
                    if attempt == 2:
                        raise

        
        if not existing_invoice:
            inv = frappe.new_doc("Sales Invoice")
            inv.naming_series = settings.sales_invoice_naming_series or "ACC-SINV-.YYYY.-"
            inv.company = settings.default_company or frappe.get_single_value("Global Defaults", "default_company")
            inv.custom_roller_booking_reference = booking_reference
            inv.custom_roller_unique_id = uniqueId
        else:
            inv = frappe.get_doc("Sales Invoice", existing_invoice)
              
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

        today_date = frappe.utils.getdate()
        inv.posting_date = earliest_date.date() if earliest_date else today_date
        if inv.due_date != latest_date.date() if latest_date else now():
            # Only set due_date if it is different from posting_date
            inv.due_date = latest_date.date() if latest_date else now()
            inv.set("payment_schedule", [])

        
        if inv.remarks != booking.get("comments"):
            inv.remarks = booking.get("comments")

        inv.taxes_and_charges = settings.default_sales_taxes_and_charges_template
        roller_discount_amount = float(booking.get("discount") or 0)

        # Reset discount first so ERPNext calculates the undiscounted totals.
        # Roller sends booking-level discount based on the final total, so when we
        # apply it on Net Total we convert it to the equivalent pre-tax amount.
        inv.apply_discount_on = ""
        inv.discount_amount = 0

        inv.set_taxes()

        inv.set_missing_values()

        if roller_discount_amount:
            pre_discount_net_total = float(inv.net_total or 0)
            pre_discount_grand_total = float(inv.grand_total or 0)

            effective_discount_amount = roller_discount_amount
            if pre_discount_grand_total > 0:
                effective_discount_amount = (
                    roller_discount_amount * pre_discount_net_total / pre_discount_grand_total
                )

            inv.apply_discount_on = "Net Total"
            inv.discount_amount = min(effective_discount_amount, pre_discount_net_total)

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
            paid_amount = float(float(booking.get("total") or 0) - float(booking.get("remainder") or 0))
            roller_payments = booking.get("payments", [])
            if roller_payments:
                inv_payments = []
                for p in roller_payments:
                    method_name = (
                        p.get("paymentMethod") or p.get("method") or p.get("type")
                        or settings.default_mode_of_payment or "Cash"
                    )
                    if not frappe.db.exists("Mode of Payment", method_name):
                        method_name = settings.default_mode_of_payment or "Cash"
                    inv_payments.append({
                        "mode_of_payment": method_name,
                        "amount": float(p.get("amount") or 0)
                    })
                inv.set("payments", inv_payments)
            else:
                inv.set("payments", [{
                    "mode_of_payment": settings.default_mode_of_payment or "Cash",
                    "amount": paid_amount
                }])
            inv.set_paid_amount()

        
        if status == "Paid":
            # inv.set_posting_time = 0
            # inv.posting_date = now()
            # inv.due_date = now()
            inv.set("payment_schedule", [])
            inv.save(ignore_permissions=True)
            # Link before submit: if submit() raises, the booking still points to its invoice
            # instead of being left orphaned.
            _link_booking(booking_doc.name, inv.name)
            inv.submit()
        else:
            inv.save(ignore_permissions=True)

        _link_booking(
            booking_doc.name, inv.name,
            "Sales Invoice {0} created successfully.".format(inv.name),
        )


    except Exception as e:
        if "booking_doc" in locals():
            _set_booking_msg(
                booking_doc.name,
                "Roller invoice processing failed. Check Error Log for details.",
            )
        frappe.log_error(frappe.get_traceback(), "Roller Webhook Error")
        # return {"status": "error", "message": str(e)}


def _booking_payload_from_api_items(booking_reference, items):
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
        "uniqueId": first["bookingUniqueId"],
    }

    if first.get("bookingCustomerId"):
        booking["customerId"] = int(first["bookingCustomerId"])

    for item in items:
        booking["items"].append({
            "bookingDate": item["bookingDate"],
            "bookingEndDate": item["bookingEndDate"],
            "bookingItemId": int(item["bookingItemId"]),
            "cost": float(item.get("cost", 0.0)),
            "createdDate": item["createdDate"],
            "discount": float(item.get("discountAmount", 0.0)),
            "groupSize": item.get("groupSize", 1),
            "modifiers": item.get("modifiers", []),
            "productId": int(item["productId"]),
            "quantity": item.get("quantity", 1),
        })

    # A deterministic event id makes repeated Fetch Bookings calls idempotent while still
    # producing a new log when Roller changes status, total, or booking items.
    event_fingerprint = json.dumps(
        {
            "bookingReference": booking_reference,
            "status": booking["status"],
            "total": booking["total"],
            "items": sorted(
                [
                    {
                        "bookingItemId": item["bookingItemId"],
                        "productId": item["productId"],
                        "quantity": item["quantity"],
                        "cost": item["cost"],
                    }
                    for item in booking["items"]
                ],
                key=lambda item: item["bookingItemId"],
            ),
        },
        sort_keys=True,
    )
    return {
        "data": {"booking": booking},
        "eventDate": first["createdDate"],
        "eventType": 1,
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, event_fingerprint)),
        "sendDate": first["createdDate"],
        "type": 1,
    }


def _roller_event_was_logged(booking_reference, event_id):
    logs = frappe.get_all(
        "Roller Booking",
        filters={"booking_reference": booking_reference},
        fields=["response"],
    )
    return any(_event_id_from_response(log.response) == event_id for log in logs)


@frappe.whitelist()
def fetch_bookings_from_roller(start_date=None, end_date=None):
    settings = frappe.get_single("Roller Settings")

    today = frappe.utils.today()
    start_date = start_date or settings.booking_start_date or today
    end_date = end_date or settings.booking_end_date or today

    base_url = settings.playground_url if settings.environment == "Playground" else settings.live_url
    access_token = settings.access_token
    token_url = f"{base_url}/token"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    page_size = 500
    all_items = []

    # Roller API only allows a 1-day window per request, so iterate day by day.
    current = datetime.strptime(str(start_date), "%Y-%m-%d").date()
    end = datetime.strptime(str(end_date), "%Y-%m-%d").date()

    frappe.logger().info("Started booking sync for dates: {} to {}".format(start_date, end_date))

    while current <= end:
        day_start = current.strftime("%Y-%m-%d")
        day_end = (current + timedelta(days=1)).strftime("%Y-%m-%d")
        page_number = 1
        retried = False

        while True:
            url = (
                f"{base_url}/data/bookingitems?"
                f"pageSize={page_size}&pageNumber={page_number}&"
                f"startDate={day_start}&endDate={day_end}"
            )
            try:
                response = requests.get(url, headers=headers, timeout=15)
                if response.status_code == 401 and not retried:
                    print("Access token expired, trying to refresh...")
                    access_token = get_new_access_token(token_url, settings.client_id, settings.client_secret)
                    if not access_token:
                        frappe.throw("Failed to refresh access token.")
                    settings.access_token = access_token
                    frappe.db.set_single_value("Roller Settings", "access_token", access_token)
                    headers["Authorization"] = f"Bearer {access_token}"
                    retried = True
                    continue

                elif response.status_code == 401 and retried:
                    frappe.throw("Unauthorized (401) even after refreshing access token.")

                if not response.ok:
                    message = ""
                    try:
                        error_json = response.json()
                        message = (
                            error_json.get("message")
                            or error_json.get("error")
                            or error_json.get("title")
                            or str(error_json)
                        )
                    except Exception:
                        message = response.text

                    frappe.log_error(
                        title="Roller API Error-1",
                        message=f"""
                        Message: {message}
                        Status: {response.status_code}
                        URL: {url}
                        Response Text: {response.text}
                        """
                    )
                    frappe.throw(_("Roller API Error-2: {0}").format(message))

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

        current += timedelta(days=1)

    # Group items by bookingReference
    grouped = defaultdict(list)
    for item in all_items:
        grouped[item["bookingReference"]].append(item)

    print(f"Total bookings fetched: {len(all_items)}")
    for booking_reference, items in grouped.items():
        booking_json = _booking_payload_from_api_items(booking_reference, items)
        existing_booking = frappe.db.exists("Roller Booking", {"booking_reference": booking_reference})

        if existing_booking:
            event_id = booking_json["id"]
            if _roller_event_was_logged(booking_reference, event_id):
                continue

            # Preserve each changed snapshot. The invoice processor can then compare this
            # log with the preceding one exactly as it does for webhook events.
            doc = frappe.new_doc("Roller Booking")
            doc.booking_reference = booking_reference
            doc.response = frappe.as_json(booking_json)
            doc.insert(ignore_permissions=True)
            make_invoice_from_roller_booking(doc.name)
            frappe.db.commit()
            continue

        frappe.logger().info("Processing booking reference: {}".format(booking_reference))

        # Create and save the Roller Booking doc
        doc = frappe.new_doc("Roller Booking")
        doc.booking_reference = booking_reference
        doc.response = frappe.as_json(booking_json)
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        make_invoice_from_roller_booking(doc.name)
        frappe.db.commit()

    frappe.logger().info("Bookings sync completed from {} to {}.".format(start_date, end_date))
    return "Bookings sync completed for given dates."
        

# Helper: Create/Get Customer
def get_or_create_customer(customer_id, name, default_address, email=None):
    try:
        customer = frappe.db.get_value("Customer", {"custom_roller_customer_id": customer_id})
        if customer:
            return frappe.get_doc("Customer", customer)

        doc = frappe.new_doc("Customer")
        doc.customer_name = name or f"Roller Customer {customer_id}"
        doc.customer_type = "Individual"
        doc.customer_group = "All Customer Groups"
        doc.territory = "All Territories"
        doc.customer_primary_address = default_address
        doc.custom_roller_customer_id = customer_id
        doc.save(ignore_permissions=True)

        if email:
            contact = frappe.new_doc("Contact")
            contact.first_name = name or f"Roller Customer {customer_id}"
            contact.append("email_ids", {"email_id": email, "is_primary": 1})
            contact.append("links", {"link_doctype": "Customer", "link_name": doc.name})
            contact.flags.ignore_permissions = True
            contact.save()
        else:
            frappe.enqueue(
                "roller.api.customer.fetch_and_attach_customer_email",
                roller_customer_id=customer_id,
                customer_doc_name=doc.name,
                queue="short",
                now=frappe.flags.in_test,
            )

        return doc
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Roller Webhook Error")


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


@frappe.whitelist()
def reconcile_booking_invoices():
    """Backfill `sales_invoice` on Roller Bookings that already have an invoice in the
    system but no link — e.g. bookings created before linking was made submit-safe.

    A booking is matched to its invoice by Roller unique id first, then by booking
    reference; in both cases we only match the original invoice (is_return = 0).
    Bookings that were never invoiced (e.g. cancelled before invoicing) are left as-is.
    """
    bookings = frappe.get_all(
        "Roller Booking",
        filters={"sales_invoice": ["in", ["", None]]},
        fields=["name", "booking_reference", "response"],
    )

    linked = 0
    for b in bookings:
        unique_id = None
        if b.response:
            try:
                unique_id = json.loads(b.response).get("data", {}).get("booking", {}).get("uniqueId")
            except Exception:
                unique_id = None

        invoice = None
        if unique_id:
            invoice = frappe.db.exists(
                "Sales Invoice", {"custom_roller_unique_id": unique_id, "is_return": 0}
            )
        if not invoice and b.booking_reference:
            invoice = frappe.db.exists(
                "Sales Invoice", {"custom_roller_booking_reference": b.booking_reference, "is_return": 0}
            )

        if invoice:
            _link_booking(b.name, invoice, _("Sales Invoice {0} linked (reconciled).").format(invoice))
            linked += 1

    frappe.db.commit()
    summary = "Reconciled {0} of {1} unlinked bookings.".format(linked, len(bookings))
    frappe.logger().info(summary)
    return summary
