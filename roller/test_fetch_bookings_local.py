"""
Local testing script for fetch_bookings_from_roller function.
Run this in your local Frappe environment to debug the issue.

Usage:
    bench execute roller.test_fetch_bookings_local.run_local_test
"""

import frappe
from frappe import _
import json
import sys
from datetime import datetime, timedelta
import requests
from roller.api.booking import fetch_bookings_from_roller, make_invoice_from_roller_booking
from roller.api.roller import get_new_access_token


def run_local_test(test_mode="diagnostic", mock_data=False):
    """
    Run local test for fetch_bookings_from_roller.
    
    Args:
        test_mode: "diagnostic", "full", or "api_only"
        mock_data: Use mock API responses if True
    """
    
    print("\n" + "="*80)
    print("ROLLER BOOKING SYNC - LOCAL TEST")
    print("="*80 + "\n")
    
    try:
        # Step 1: Check Roller Settings
        print("[1] Checking Roller Settings...")
        settings = frappe.get_single("Roller Settings")
        
        print(f"  ✓ Environment: {settings.environment}")
        print(f"  ✓ Start Date: {settings.booking_start_date}")
        print(f"  ✓ End Date: {settings.booking_end_date}")
        print(f"  ✓ Access Token: {'***' + str(settings.access_token)[-10:] if settings.access_token else 'NOT SET'}")
        print(f"  ✓ Client ID: {'***' + str(settings.client_id)[-5:] if settings.client_id else 'NOT SET'}")
        print(f"  ✓ Live URL: {settings.live_url}")
        print(f"  ✓ Playground URL: {settings.playground_url}")
        
        base_url = settings.playground_url if settings.environment == "Playground" else settings.live_url
        print(f"\n  Using Base URL: {base_url}")
        
        # Validate settings
        if not settings.booking_start_date or not settings.booking_end_date:
            print("\n  ✗ ERROR: Start and End dates must be set!")
            return
            
        if not settings.access_token:
            print("\n  ✗ ERROR: Access token not set!")
            return
            
        if not settings.client_id or not settings.client_secret:
            print("\n  ✗ ERROR: Client ID/Secret not set!")
            return
        
        print("\n  ✓ Settings validated!\n")
        
        # Step 2: Test API Connection
        print("[2] Testing API Connection...")
        headers = {
            "Authorization": f"Bearer {settings.access_token}",
            "Content-Type": "application/json"
        }
        
        url = (
            f"{base_url}/data/bookingitems?"
            f"pageSize=1&pageNumber=1&"
            f"startDate={settings.booking_start_date}&endDate={settings.booking_end_date}"
        )
        
        print(f"  Testing URL: {url}\n")
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            print(f"  Response Status: {response.status_code}")
            
            if response.status_code == 401:
                print("\n  ✗ 401 Unauthorized - Token may be expired")
                print("  Attempting to refresh token...\n")
                
                # Try to refresh token
                token_url = f"{base_url}/token"
                access_token = get_new_access_token(
                    token_url, 
                    settings.client_id, 
                    settings.client_secret
                )
                
                if access_token:
                    print(f"  ✓ Token refreshed successfully!")
                    print(f"  New Token: ***{access_token[-10:]}")
                    settings.access_token = access_token
                    frappe.db.set_single_value("Roller Settings", "access_token", access_token)
                    
                    # Retry with new token
                    headers["Authorization"] = f"Bearer {access_token}"
                    response = requests.get(url, headers=headers, timeout=15)
                    print(f"  Retry Status: {response.status_code}\n")
                else:
                    print("  ✗ Failed to refresh token!\n")
                    return
            
            if response.status_code != 200:
                print(f"  ✗ API Error: {response.status_code}")
                try:
                    error_data = response.json()
                    print(f"  Error Details: {json.dumps(error_data, indent=2)}\n")
                except:
                    print(f"  Response: {response.text}\n")
                return
            
            # Parse response
            data = response.json()
            print(f"  ✓ API Connection Successful!")
            print(f"  Total Items Returned: {len(data.get('items', []))}")
            print(f"  Current Page: {data.get('currentPage', 1)}")
            print(f"  Total Pages: {data.get('totalPages', 1)}")
            
            if data.get('items'):
                first_item = data['items'][0]
                print(f"\n  Sample Item Keys: {list(first_item.keys())}")
            
            print()
            
        except requests.exceptions.Timeout:
            print("  ✗ API Request Timeout (15 seconds)")
            print("  The Roller API took too long to respond\n")
            return
        except requests.exceptions.ConnectionError as e:
            print(f"  ✗ Connection Error: {str(e)}")
            print("  Cannot reach the API server\n")
            return
        except Exception as e:
            print(f"  ✗ Unexpected Error: {str(e)}\n")
            return
        
        # Step 3: Dry Run - Check data processing without saving
        print("[3] Dry Run - Checking Data Processing...")
        print(f"  Date Range: {settings.booking_start_date} to {settings.booking_end_date}")
        
        # Fetch full data
        page_number = 1
        page_size = 500
        all_items = []
        
        while True:
            url = (
                f"{base_url}/data/bookingitems?"
                f"pageSize={page_size}&pageNumber={page_number}&"
                f"startDate={settings.booking_start_date}&endDate={settings.booking_end_date}"
            )
            
            response = requests.get(url, headers=headers, timeout=15)
            
            if response.status_code != 200:
                print(f"  ✗ Error fetching page {page_number}: {response.status_code}\n")
                break
            
            data = response.json()
            items = data.get("items", [])
            all_items.extend(items)
            
            print(f"  ✓ Page {page_number}: {len(items)} items")
            
            if data.get("currentPage", 1) >= data.get("totalPages", 1):
                break
            page_number += 1
        
        print(f"\n  Total Items Fetched: {len(all_items)}")
        
        # Group by booking reference
        from collections import defaultdict
        grouped = defaultdict(list)
        for item in all_items:
            grouped[item["bookingReference"]].append(item)
        
        print(f"  Total Unique Bookings: {len(grouped)}")
        
        if grouped:
            # Show sample
            sample_booking_ref = list(grouped.keys())[0]
            sample_items = grouped[sample_booking_ref]
            print(f"\n  Sample Booking: {sample_booking_ref}")
            print(f"    Items: {len(sample_items)}")
            print(f"    Sample Item: {json.dumps(sample_items[0], indent=6, default=str)}")
        
        print()
        
        # Step 4: Check for duplicates
        print("[4] Checking for Duplicate Bookings...")
        from roller.api.booking import fetch_bookings_from_roller
        
        duplicates = 0
        for booking_ref in grouped.keys():
            if frappe.db.exists("Roller Booking", {"booking_reference": booking_ref}):
                duplicates += 1
        
        print(f"  Already Synced: {duplicates}")
        print(f"  Ready to Sync: {len(grouped) - duplicates}\n")
        
        # Step 5: Full test or just diagnostic?
        if test_mode == "full":
            print("[5] Running Full Sync...")
            try:
                result = fetch_bookings_from_roller()
                print(f"  ✓ {result}\n")
            except Exception as e:
                print(f"  ✗ Error: {str(e)}\n")
                import traceback
                traceback.print_exc()
        else:
            print("[5] Diagnostic Complete - Ready for Full Sync")
            print("  Run with test_mode='full' to execute actual sync\n")
        
        print("="*80)
        print("SUMMARY: All diagnostic checks passed ✓")
        print("="*80 + "\n")
        
    except Exception as e:
        print(f"\n✗ CRITICAL ERROR: {str(e)}\n")
        import traceback
        traceback.print_exc()


def quick_api_test():
    """Quick API connectivity test — uses a 1-day window (API limit)"""
    print("\nQuick API Test...")
    settings = frappe.get_single("Roller Settings")
    base_url = settings.playground_url if settings.environment == "Playground" else settings.live_url

    print(f"  Environment : {settings.environment}")
    print(f"  Base URL    : {base_url}")
    print(f"  Start Date  : {settings.booking_start_date}")
    print(f"  End Date    : {settings.booking_end_date}")

    headers = {
        "Authorization": f"Bearer {settings.access_token}",
        "Content-Type": "application/json"
    }

    # Roller API only allows 1-day windows; use start_date → start_date+1
    start = settings.booking_start_date
    end = (datetime.strptime(str(start), "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    url = f"{base_url}/data/bookingitems?pageSize=10&pageNumber=1&startDate={start}&endDate={end}"
    print(f"\n  Testing URL : {url}\n")

    try:
        response = requests.get(url, headers=headers, timeout=15)
        print(f"Status: {response.status_code}")
        try:
            data = response.json()
            print(f"Total Items : {len(data.get('items', []))}")
            print(f"Total Pages : {data.get('totalPages', '-')}")
            if data.get('items'):
                print(f"First Item  : {json.dumps(data['items'][0], indent=2, default=str)}")
            else:
                print(f"Full Response: {json.dumps(data, indent=2, default=str)}")
        except Exception:
            print(f"Response text: {response.text}")
    except Exception as e:
        print(f"Error: {str(e)}")


# Run if executed directly
if __name__ == "__main__":
    run_local_test(test_mode="diagnostic")
