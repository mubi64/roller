import frappe
from frappe import _
import requests
from roller.api.roller import get_new_access_token

@frappe.whitelist()
def fetch_products_from_roller():
    settings = frappe.get_single("Roller Settings")

    base_url = settings.playground_url if settings.environment == "Playground" else settings.live_url
    access_token = settings.access_token
    token_url = f"{base_url}/token"

    def _get_headers(token):
        return {"Authorization": f"Bearer {token}"}


    page = 1
    page_size = 500
    retried = False  # Flag to track if we've retried

    while True:
        url = f"{base_url}/data/products?pageSize={page_size}&pageNumber={page}"
        response = requests.get(url, headers=_get_headers(access_token))

        if response.status_code == 401 and not retried:
            # Try getting new token and retry once
            access_token = get_new_access_token(token_url, settings.client_id, settings.client_secret)
            if not access_token:
                frappe.throw("Failed to refresh access token.")
            # Save new token in settings
            settings.access_token = access_token
            frappe.db.set_single_value("Roller Settings", "access_token", access_token)

            retried = True
            continue  # Retry the same request with new token
        elif response.status_code == 401 and retried:
                frappe.throw("Unauthorized (401) even after refreshing access token.")
        
        if not response.ok:
            try:
                message = response.json().get("message", response.text)
            except Exception:
                message = response.text
            frappe.log_error(f"Roller API Error: {message}")
            frappe.throw(_("Roller API Error: {0}").format(message))

        data = response.json()
        for product in data.get("items", []):
            create_or_update_item(product)

        if page >= data.get("totalPages", 1):
            break

        page += 1

    return "Products successfully synced from Roller."


def create_or_update_item(product):
    product_id = product.get("productId")
    name = product.get("name")
    item_group = create_or_get_item_group(product.get("productType"))

    existing_item = frappe.db.exists("Item", {"custom_roller_product_id": product_id})

    if existing_item:
        item = frappe.get_doc("Item", existing_item)
    else:
        item = frappe.new_doc("Item")
        item.item_code = product_id

    # Update common fields
    item.item_name = name
    item.description = product.get("reportingCategoryName", name)
    item.item_group = item_group
    item.is_stock_item = 0
    item.stock_uom = "Nos"
    item.custom_roller_product_id = product_id
    item.disabled = product.get("productStatus") != "Published"

    if "price" in product:
        item.standard_rate = product["price"]

    item.save(ignore_permissions=True)

def create_or_get_item_group(product_type):
    item_group = frappe.db.exists("Item Group", {"item_group_name": product_type})
    if not item_group:
        item_group = frappe.get_doc({
            "doctype": "Item Group",
            "item_group_name": product_type,
            "is_group": 0
        })
        item_group.insert(ignore_permissions=True)
        return item_group.name
    return item_group
