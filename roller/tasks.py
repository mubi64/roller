import frappe
from datetime import timedelta

def fetch_customers_from_roller_task():
    frappe.enqueue("roller.api.customer.fetch_customers_from_roller", queue='long')

def fetch_products_from_roller_task():
    frappe.enqueue("roller.api.product.fetch_products_from_roller", queue='long')

def fetch_bookings_from_roller_task():
    yesterday = (frappe.utils.getdate() - timedelta(days=1)).strftime("%Y-%m-%d")
    frappe.enqueue(
        "roller.api.booking.fetch_bookings_from_roller",
        start_date=yesterday,
        end_date=yesterday,
        queue='long'
    )

def fetch_data_from_roller():
    fetch_customers_from_roller_task()
    fetch_products_from_roller_task()
    fetch_bookings_from_roller_task()
