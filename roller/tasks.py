import frappe

def fetch_customers_from_roller_task():
    frappe.enqueue("roller.api.customer.fetch_customers_from_roller", queue='long')

def fetch_products_from_roller_task():
    frappe.enqueue("roller.api.product.fetch_products_from_roller", queue='long')

def fetch_bookings_from_roller_task():
    frappe.enqueue("roller.api.booking.fetch_bookings_from_roller", queue='long')

def fetch_data_from_roller():
    fetch_customers_from_roller_task()
    fetch_products_from_roller_task()
    fetch_bookings_from_roller_task()
