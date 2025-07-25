import frappe
import requests
from frappe import _
from frappe.utils import get_url

@frappe.whitelist()
def create_roller_webhook(docname):
    doc = frappe.get_doc("Roller Webhook", docname)
    settings = frappe.get_single("Roller Settings")

    base_url = settings.playground_url if settings.environment == "Playground" else settings.live_url
    url = f"{base_url}/webhooks"

    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {settings.access_token}", "Content-Type": "application/json"},
            json=frappe.parse_json(doc.request_payload)
        )
        response.raise_for_status()
        data = response.json()
        doc.response = frappe.as_json(data)
        doc.roller_webhook_id = data.get("webhookId")
        doc.save()
        return data
    except requests.RequestException as e:
        frappe.throw(_("Failed to create webhook: ") + str(e))

    
@frappe.whitelist()
def delete_roller_webhook(docname):
    doc = frappe.get_doc("Roller Webhook", docname)
    settings = frappe.get_single("Roller Settings")

    if not doc.roller_webhook_id:
        frappe.throw(_("Webhook ID not found."))

    base_url = settings.playground_url if settings.environment == "Playground" else settings.live_url
    url = f"{base_url}/webhooks/{doc.roller_webhook_id}"

    try:
        response = requests.delete(
            url,
            headers={"Authorization": f"Bearer {settings.access_token}"}
        )
        response.raise_for_status()
        doc.response = frappe.as_json({"message": "Deleted Successfully"})
        doc.roller_webhook_id = None
        doc.save()
        return {"message": "Deleted Successfully"}
    except requests.RequestException as e:
        frappe.throw(_("Failed to delete webhook: ") + str(e))
