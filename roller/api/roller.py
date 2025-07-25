import frappe
import requests
import json

@frappe.whitelist()
def get_access_token(environment, client_id, client_secret, playground_url, live_url):
    url = playground_url if environment == "Playground" else live_url
    token_url = f"{url}/token"

    payload = {
        "client_id": client_id,
        "client_secret": client_secret
    }

    try:
        response = requests.post(token_url, data=json.dumps(payload), headers={
            "Content-Type": "application/json"
        }, timeout=15)

        response.raise_for_status()
        token_data = response.json()
        access_token = token_data.get("access_token")

        if not access_token:
            frappe.throw("Access Token not found in response.")

        # Optionally, save to DocType
        doc = frappe.get_single("Roller Settings")
        doc.access_token = access_token
        doc.save(ignore_permissions=True)

        return access_token

    except requests.exceptions.RequestException as e:
        frappe.throw(f"Failed to fetch access token: {e}")

def get_new_access_token(token_url, client_id, client_secret):
    try:
        response = requests.post(
            token_url,
            json={"client_id": client_id, "client_secret": client_secret},
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        response.raise_for_status()
        token_data = response.json()
        return token_data.get("access_token")

    except requests.exceptions.RequestException as e:
        frappe.log_error(frappe.get_traceback(), "Roller Token Refresh Error")
        return None

