import frappe
import requests
from frappe import _
from frappe.utils import get_url
from roller.api.roller import get_new_access_token


def _get_fresh_token(settings):
    base_url = settings.playground_url if settings.environment == "Playground" else settings.live_url
    token = get_new_access_token(f"{base_url}/token", settings.client_id, settings.client_secret)
    if token:
        settings.access_token = token
        settings.save(ignore_permissions=True)
    return token or settings.access_token


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
        if response.status_code == 401:
            token = _get_fresh_token(settings)
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
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
        if response.status_code == 401:
            token = _get_fresh_token(settings)
            response = requests.delete(
                url,
                headers={"Authorization": f"Bearer {token}"}
            )
        response.raise_for_status()
        doc.response = frappe.as_json({"message": "Deleted Successfully"})
        doc.roller_webhook_id = None
        doc.save()
        return {"message": "Deleted Successfully"}
    except requests.RequestException as e:
        frappe.throw(_("Failed to delete webhook: ") + str(e))
