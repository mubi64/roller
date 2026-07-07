import frappe
from frappe import _
import requests
from datetime import datetime, timedelta
from roller.api.roller import get_new_access_token

@frappe.whitelist()
def fetch_customers_from_roller():
    settings = frappe.get_single("Roller Settings")

    today = frappe.utils.today()
    start_date = settings.customer_start_date or today
    end_date = settings.customer_end_date or today

    # Pre-load all existing roller customer IDs in one query to avoid per-customer DB lookups.
    existing_customers = {
        str(r.custom_roller_customer_id): r.name
        for r in frappe.get_all(
            "Customer",
            filters=[["custom_roller_customer_id", "!=", ""]],
            fields=["name", "custom_roller_customer_id"]
        )
    }

    # Roller API only allows a 1-day window per request, so iterate day by day.
    current = datetime.strptime(str(start_date), "%Y-%m-%d").date()
    end = datetime.strptime(str(end_date), "%Y-%m-%d").date()

    frappe.logger().info("Started customer sync for dates: {} to {}".format(start_date, end_date))
    while current <= end:
        day_start = current.strftime("%Y-%m-%d")
        day_end = (current + timedelta(days=1)).strftime("%Y-%m-%d")
        fetch_and_save_customers(day_start, day_end, settings, existing_customers)
        current += timedelta(days=1)

    frappe.logger().info("Customer sync completed until {}.".format(end_date))
    return "Customer sync completed for given dates."


def fetch_and_save_customers(start_date, end_date, settings, existing_customers):
    base_url = settings.playground_url if settings.environment == "Playground" else settings.live_url
    access_token = settings.access_token
    token_url = f"{base_url}/token"

    page_number = 1
    page_size = 500
    retried = False
    while True:
        url = (
            f"{base_url}/data/customers?"
            f"pageSize={page_size}&pageNumber={page_number}&"
            f"startDate={start_date}&endDate={end_date}"
        )

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.get(url, headers=headers, timeout=15)

            if response.status_code == 401 and not retried:
                access_token = get_new_access_token(token_url, settings.client_id, settings.client_secret)
                if not access_token:
                    frappe.throw("Failed to refresh access token.")
                settings.access_token = access_token
                frappe.db.set_single_value("Roller Settings", "access_token", access_token)
                retried = True
                continue

            elif response.status_code == 401 and retried:
                frappe.throw("Unauthorized (401) even after refreshing access token.")

            if not response.ok:
                try:
                    message = response.json().get("message", response.text)
                except Exception:
                    message = response.text
                frappe.log_error(f"Roller API Error: {message}")
                frappe.throw(_("Roller API Error: {0}").format(message))

            response.raise_for_status()

            data = response.json()
            customers = data.get("items", [])

            frappe.logger().info("Processing {} customers on page {}".format(len(customers), page_number))

            for i, c in enumerate(customers):
                save_customer_to_erpnext(c, existing_customers)
                if i % 50 == 49:
                    frappe.db.commit()

            frappe.db.commit()

            if data.get("currentPage", 1) >= data.get("totalPages", 1):
                break

            page_number += 1

        except requests.exceptions.RequestException as e:
            frappe.log_error(frappe.get_traceback(), "Roller Fetch Customers Error")
            frappe.throw(f"Failed to fetch customers from Roller API: {e}")


def save_customer_to_erpnext(c, existing_customers):
    roller_customer_id = str(c.get("customerId") or "")
    if not roller_customer_id:
        return

    customer_name = f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
    email = c.get("email")

    if roller_customer_id in existing_customers:
        # Skip update — customer already synced
        return

    customer = frappe.new_doc("Customer")
    customer.customer_name = customer_name or f"Roller Customer {roller_customer_id}"
    customer.customer_type = "Individual"
    customer.customer_group = "All Customer Groups"
    customer.custom_roller_customer_id = roller_customer_id
    customer.flags.ignore_permissions = True
    customer.save()

    if email:
        contact = frappe.new_doc("Contact")
        contact.first_name = c.get("firstName", "") or customer.customer_name
        contact.last_name = c.get("lastName", "")
        contact.append("email_ids", {
            "email_id": email,
            "is_primary": 1
        })
        contact.append("links", {
            "link_doctype": "Customer",
            "link_name": customer.name
        })
        contact.flags.ignore_permissions = True
        contact.save()

    existing_customers[roller_customer_id] = customer.name


def fetch_and_attach_customer_email(roller_customer_id, customer_doc_name):
    """Search recent Roller customer pages for roller_customer_id and attach a Contact with email.

    The Roller API requires startDate + endDate, so we search backwards day-by-day from today
    up to MAX_DAYS_BACK. Stops as soon as the customer is found.
    Called as a background job from get_or_create_customer.
    """
    from datetime import date, timedelta

    MAX_DAYS_BACK = 30

    try:
        customer_doc = frappe.get_doc("Customer", customer_doc_name)

        settings = frappe.get_single("Roller Settings")
        base_url = settings.playground_url if settings.environment == "Playground" else settings.live_url
        access_token = settings.access_token
        token_url = f"{base_url}/token"
        retried = False

        today = date.today()

        for days_back in range(MAX_DAYS_BACK):
            day = today - timedelta(days=days_back)
            start_date = day.strftime("%Y-%m-%d")
            end_date = (day + timedelta(days=1)).strftime("%Y-%m-%d")

            url = (
                f"{base_url}/data/customers?"
                f"pageSize=500&pageNumber=1&startDate={start_date}&endDate={end_date}"
            )
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            response = requests.get(url, headers=headers, timeout=15)

            if response.status_code == 401 and not retried:
                access_token = get_new_access_token(token_url, settings.client_id, settings.client_secret)
                if not access_token:
                    return
                frappe.db.set_single_value("Roller Settings", "access_token", access_token)
                headers["Authorization"] = f"Bearer {access_token}"
                response = requests.get(url, headers=headers, timeout=15)
                retried = True

            if not response.ok:
                continue

            for c in response.json().get("items", []):
                if str(c.get("customerId")) != str(roller_customer_id):
                    continue
                email = c.get("email")
                if email:
                    contact = frappe.new_doc("Contact")
                    contact.first_name = c.get("firstName", "") or customer_doc.customer_name
                    contact.last_name = c.get("lastName", "")
                    contact.append("email_ids", {"email_id": email, "is_primary": 1})
                    contact.append("links", {"link_doctype": "Customer", "link_name": customer_doc.name})
                    contact.flags.ignore_permissions = True
                    contact.save()
                    frappe.db.commit()
                return  # found the customer (even if no email), stop searching

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Roller Customer Email Fetch Error")
