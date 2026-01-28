import frappe
from frappe import _
import requests
from datetime import datetime, timedelta
from roller.api.roller import get_new_access_token

@frappe.whitelist()
def fetch_customers_from_roller():
    settings = frappe.get_single("Roller Settings")

    start_date = settings.customer_start_date
    end_date = settings.customer_end_date
    today = frappe.utils.today()

    if not start_date or not end_date:
        frappe.throw("Start and End dates must be set in Roller Settings.")

    # Loop until start_date reaches today
    while True:
        # Call the API for the current date window
        fetch_and_save_customers(start_date, end_date, settings)

        # If today has been reached, break the loop (don't update date fields)
        if start_date == today:
            break

        # Move the date window forward by 1 day
        start_date = str(datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=1))[:10]
        end_date = str(datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1))[:10]

        # Update the fields in Roller Settings
        settings.customer_start_date = start_date
        settings.customer_end_date = end_date
        settings.save(ignore_permissions=True)

    frappe.logger().info("Customer sync completed until {}.".format(today))
    return "Customer sync completed until today."


def fetch_and_save_customers(start_date, end_date, settings):
    base_url = settings.playground_url if settings.environment == "Playground" else settings.live_url
    access_token = settings.access_token
    token_url = f"{base_url}/token"

    page_number = 1
    page_size = 500
    retried = False  # Flag to track if we've retried
    frappe.logger().info("Started customer sync for dates: {} to {}".format(start_date, end_date))
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
                frappe.log_error(f"Roller API Error: {message}")
                frappe.throw(_("Roller API Error: {0}").format(message))    


            response.raise_for_status()

            data = response.json()
            customers = data.get("items", [])

            frappe.logger().info("Processing {} customers on page {}".format(len(customers), page_number))
            
            for c in customers:
                save_customer_to_erpnext(c)

            if data.get("currentPage", 1) >= data.get("totalPages", 1):
                break

            page_number += 1

        except requests.exceptions.RequestException as e:
            frappe.log_error(frappe.get_traceback(), "Roller Fetch Customers Error")
            frappe.throw(f"Failed to fetch customers from Roller API: {e}")



def save_customer_to_erpnext(c):
    roller_customer_id = c.get("customerId")
    if not roller_customer_id:
        return

    customer_name = f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
    email = c.get("email")

    existing = frappe.get_all("Customer", filters={"custom_roller_customer_id": roller_customer_id}, limit=1)

    if existing:
        customer = frappe.get_doc("Customer", existing[0].name)
        customer.customer_name = customer_name
        customer.email_id = email
    else:
        customer = frappe.new_doc("Customer")
        customer.customer_name = customer_name or f"Roller Customer {roller_customer_id}"
        customer.customer_type = "Individual"
        customer.customer_group = "All Customer Groups"
        customer.email_id = email
        customer.custom_roller_customer_id = roller_customer_id

    customer.flags.ignore_permissions = True
    customer.save()
