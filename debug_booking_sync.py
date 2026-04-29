"""
Enhanced debugging utilities for fetch_bookings_from_roller.

Usage:
    bench execute roller.debug_booking_sync.check_settings
    bench execute roller.debug_booking_sync.check_api_response
    bench execute roller.debug_booking_sync.check_data_parsing
    bench execute roller.debug_booking_sync.check_db_state
"""

import frappe
import json
import requests
from datetime import datetime
from roller.api.roller import get_new_access_token


def check_settings():
    """Verify all Roller Settings are configured correctly"""
    print("\n" + "="*60)
    print("CHECKING ROLLER SETTINGS")
    print("="*60 + "\n")
    
    try:
        settings = frappe.get_single("Roller Settings")
        
        checks = {
            "Environment": settings.environment,
            "Live URL": settings.live_url,
            "Playground URL": settings.playground_url,
            "Booking Start Date": settings.booking_start_date,
            "Booking End Date": settings.booking_end_date,
            "Access Token": "SET" if settings.access_token else "NOT SET",
            "Client ID": "SET" if settings.client_id else "NOT SET",
            "Client Secret": "SET" if settings.client_secret else "NOT SET",
            "Default Company": settings.default_company,
            "Default Customer": settings.default_customer,
            "Default Address": settings.default_address,
            "Sales Invoice Template": settings.default_sales_taxes_and_charges_template,
            "Mode of Payment": settings.default_mode_of_payment,
        }
        
        for key, value in checks.items():
            status = "✓" if value else "✗"
            print(f"  {status} {key}: {value}")
        
        # Validate date range
        print("\n  Date Range Validation:")
        start = settings.booking_start_date
        end = settings.booking_end_date
        
        if start and end:
            delta = (end - start).days
            print(f"    Start: {start}")
            print(f"    End: {end}")
            print(f"    Days: {delta}")
            
            if delta < 0:
                print("    ✗ ERROR: Start date is after end date!")
            elif delta > 365:
                print("    ⚠ WARNING: Range is > 365 days (may hit API limits)")
        
        print("\n" + "="*60 + "\n")
        
    except Exception as e:
        print(f"✗ Error: {str(e)}\n")


def check_api_response():
    """Test API endpoint and check response format"""
    print("\n" + "="*60)
    print("CHECKING API RESPONSE")
    print("="*60 + "\n")
    
    try:
        settings = frappe.get_single("Roller Settings")
        base_url = settings.playground_url if settings.environment == "Playground" else settings.live_url
        
        print(f"  Environment: {settings.environment}")
        print(f"  Base URL: {base_url}")
        print(f"  Date Range: {settings.booking_start_date} to {settings.booking_end_date}\n")
        
        # Test with current token
        headers = {
            "Authorization": f"Bearer {settings.access_token}",
            "Content-Type": "application/json"
        }
        
        url = (
            f"{base_url}/data/bookingitems?"
            f"pageSize=1&pageNumber=1&"
            f"startDate={settings.booking_start_date}&endDate={settings.booking_end_date}"
        )
        
        print(f"  Testing: {url}\n")
        
        response = requests.get(url, headers=headers, timeout=15)
        print(f"  Status Code: {response.status_code}")
        
        if response.status_code == 401:
            print("  ✗ 401 Unauthorized - Token is expired or invalid\n")
            print("  Attempting token refresh...\n")
            
            token_url = f"{base_url}/token"
            access_token = get_new_access_token(
                token_url,
                settings.client_id,
                settings.client_secret
            )
            
            if access_token:
                print(f"  ✓ Token refreshed!")
                settings.access_token = access_token
                frappe.db.set_single_value("Roller Settings", "access_token", access_token)
                
                headers["Authorization"] = f"Bearer {access_token}"
                response = requests.get(url, headers=headers, timeout=15)
                print(f"  Retry Status: {response.status_code}\n")
            else:
                print("  ✗ Failed to refresh token\n")
                return
        
        if response.status_code != 200:
            print(f"  Response: {response.text}\n")
            print("="*60 + "\n")
            return
        
        # Check response format
        data = response.json()
        print(f"  Response Keys: {list(data.keys())}")
        print(f"  Items Count: {len(data.get('items', []))}")
        print(f"  Current Page: {data.get('currentPage')}")
        print(f"  Total Pages: {data.get('totalPages')}")
        
        if data.get('items'):
            print(f"\n  First Item Keys:")
            for key in data['items'][0].keys():
                print(f"    - {key}")
            
            print(f"\n  First Item Sample:")
            print(f"    {json.dumps(data['items'][0], indent=6, default=str)}")
        
        print("\n" + "="*60 + "\n")
        
    except requests.exceptions.Timeout:
        print("  ✗ Timeout: API took too long to respond (>15 seconds)\n")
    except requests.exceptions.ConnectionError as e:
        print(f"  ✗ Connection Error: {str(e)}\n")
    except Exception as e:
        print(f"  ✗ Error: {str(e)}\n")


def check_data_parsing():
    """Test data parsing and transformation logic"""
    print("\n" + "="*60)
    print("CHECKING DATA PARSING")
    print("="*60 + "\n")
    
    try:
        settings = frappe.get_single("Roller Settings")
        base_url = settings.playground_url if settings.environment == "Playground" else settings.live_url
        
        headers = {
            "Authorization": f"Bearer {settings.access_token}",
            "Content-Type": "application/json"
        }
        
        url = (
            f"{base_url}/data/bookingitems?"
            f"pageSize=100&pageNumber=1&"
            f"startDate={settings.booking_start_date}&endDate={settings.booking_end_date}"
        )
        
        print(f"  Fetching sample data...\n")
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            print(f"  ✗ API Error: {response.status_code}\n")
            return
        
        data = response.json()
        items = data.get('items', [])
        print(f"  ✓ Fetched {len(items)} items\n")
        
        # Test grouping
        from collections import defaultdict
        grouped = defaultdict(list)
        for item in items:
            grouped[item["bookingReference"]].append(item)
        
        print(f"  ✓ Grouped into {len(grouped)} bookings\n")
        
        if grouped:
            sample_ref = list(grouped.keys())[0]
            sample_items = grouped[sample_ref]
            
            print(f"  Sample Booking Reference: {sample_ref}")
            print(f"  Items in booking: {len(sample_items)}\n")
            
            # Test transformation
            first = sample_items[0]
            try:
                booking = {
                    "amountOwing": 0.0,
                    "bookingReference": sample_ref,
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
                    "uniqueId": first["bookingUniqueId"]
                }
                
                if first.get("bookingCustomerId"):
                    booking["customerId"] = int(first["bookingCustomerId"])
                
                print(f"  ✓ Booking transformation successful")
                print(f"  Transformed data keys: {list(booking.keys())}\n")
                
                print(f"  Sample transformed booking:")
                print(f"    {json.dumps(booking, indent=6, default=str)}\n")
                
            except Exception as e:
                print(f"  ✗ Transformation error: {str(e)}\n")
                import traceback
                traceback.print_exc()
        
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"  ✗ Error: {str(e)}\n")


def check_db_state():
    """Check database state and existing bookings"""
    print("\n" + "="*60)
    print("CHECKING DATABASE STATE")
    print("="*60 + "\n")
    
    try:
        # Check Roller Booking count
        booking_count = frappe.db.count("Roller Booking")
        print(f"  Total Roller Bookings: {booking_count}")
        
        # Check recent bookings
        recent = frappe.get_all(
            "Roller Booking",
            order_by="creation desc",
            limit=5,
            fields=["name", "booking_reference", "sales_invoice", "creation"]
        )
        
        if recent:
            print(f"\n  Recent Bookings:")
            for rb in recent:
                invoice_status = f"→ {rb.sales_invoice}" if rb.sales_invoice else "NO INVOICE"
                print(f"    {rb.name} ({rb.booking_reference}) {invoice_status}")
        
        # Check Sales Invoice count
        invoice_count = frappe.db.count("Sales Invoice", {"custom_roller_unique_id": ["!=", ""]})
        print(f"\n  Sales Invoices with Roller ID: {invoice_count}")
        
        # Check settings
        settings = frappe.get_single("Roller Settings")
        print(f"\n  Roller Settings:")
        print(f"    Date Range: {settings.booking_start_date} to {settings.booking_end_date}")
        print(f"    Default Company: {settings.default_company}")
        print(f"    Default Customer: {settings.default_customer}")
        
        # Check if defaults exist
        if settings.default_company:
            company_exists = frappe.db.exists("Company", settings.default_company)
            print(f"    Company Exists: {'✓' if company_exists else '✗'}")
        
        if settings.default_customer:
            customer_exists = frappe.db.exists("Customer", settings.default_customer)
            print(f"    Customer Exists: {'✓' if customer_exists else '✗'}")
        
        if settings.default_address:
            address_exists = frappe.db.exists("Address", settings.default_address)
            print(f"    Address Exists: {'✓' if address_exists else '✗'}")
        
        print("\n" + "="*60 + "\n")
        
    except Exception as e:
        print(f"  ✗ Error: {str(e)}\n")


# Export functions
__all__ = [
    'check_settings',
    'check_api_response', 
    'check_data_parsing',
    'check_db_state'
]
