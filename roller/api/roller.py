import frappe
import requests
import json


def _fetch_token(token_url, client_id, client_secret):
    """
    Roller uses a .NET (ASP.NET Core) API that expects camelCase JSON fields.
    Try camelCase first, then snake_case as fallback.
    Returns (access_token, error_message).
    """
    attempts = [
        {"clientId": client_id, "clientSecret": client_secret},       # camelCase (Roller .NET API)
        {"client_id": client_id, "client_secret": client_secret},     # snake_case fallback
    ]

    errors = []
    for payload in attempts:
        response = requests.post(
            token_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        if response.ok:
            return response.json().get("access_token"), None
        errors.append(f"payload={list(payload.keys())} → {response.status_code}: {response.text}")

    return None, " | ".join(errors)


@frappe.whitelist()
def get_access_token(environment, client_id, client_secret, playground_url, live_url):
    url = playground_url if environment == "Playground" else live_url
    token_url = f"{url}/token"

    try:
        access_token, error = _fetch_token(token_url, client_id, client_secret)
        if error:
            frappe.throw(f"Failed to fetch access token — {error}")
        if not access_token:
            frappe.throw("Access token not found in Roller response.")

        doc = frappe.get_single("Roller Settings")
        doc.access_token = access_token
        doc.save(ignore_permissions=True)
        return access_token

    except frappe.ValidationError:
        raise
    except requests.exceptions.RequestException as e:
        frappe.throw(f"Failed to fetch access token: {e}")


def get_new_access_token(token_url, client_id, client_secret):
    try:
        access_token, error = _fetch_token(token_url, client_id, client_secret)
        if error:
            frappe.log_error(f"Token refresh failed — {error}", "Roller Token Refresh Error")
        return access_token
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Roller Token Refresh Error")
        return None
