"""
Fix for Roller Settings - Initialize or repair missing date fields.

Usage:
    bench execute roller.fix_roller_settings.initialize_date_fields
    bench execute roller.fix_roller_settings.diagnose_settings
"""

import frappe
from datetime import datetime, timedelta


def diagnose_settings():
    """Check current state of Roller Settings"""
    print("\n" + "="*60)
    print("ROLLER SETTINGS DIAGNOSIS")
    print("="*60 + "\n")
    
    try:
        settings = frappe.get_single("Roller Settings")
        
        print("Authentication:")
        print(f"  Environment: {settings.environment}")
        print(f"  Access Token: {'SET' if settings.access_token else '❌ NOT SET'}")
        print(f"  Client ID: {'SET' if settings.client_id else '❌ NOT SET'}")
        print(f"  Client Secret: {'SET' if settings.client_secret else '❌ NOT SET'}\n")
        
        print("Date Fields (for Customers):")
        print(f"  customer_start_date: {settings.customer_start_date or '❌ NOT SET'}")
        print(f"  customer_end_date: {settings.customer_end_date or '❌ NOT SET'}\n")
        
        print("Date Fields (for Bookings):")
        print(f"  booking_start_date: {settings.booking_start_date or '❌ NOT SET'}")
        print(f"  booking_end_date: {settings.booking_end_date or '❌ NOT SET'}\n")
        
        print("Default Entities:")
        print(f"  default_company: {settings.default_company or '❌ NOT SET'}")
        print(f"  default_customer: {settings.default_customer or '❌ NOT SET'}")
        print(f"  default_address: {settings.default_address or '❌ NOT SET'}")
        print(f"  default_sales_taxes_and_charges_template: {settings.default_sales_taxes_and_charges_template or '❌ NOT SET'}")
        print(f"  default_mode_of_payment: {settings.default_mode_of_payment or '❌ NOT SET'}\n")
        
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"Error: {str(e)}\n")


def initialize_date_fields(days_back=30):
    """
    Initialize missing date fields with sensible defaults.
    
    Args:
        days_back: Number of days to go back for start_date (default: 30)
    """
    print("\n" + "="*60)
    print("INITIALIZING ROLLER SETTINGS DATE FIELDS")
    print("="*60 + "\n")
    
    try:
        settings = frappe.get_single("Roller Settings")
        today = datetime.now().date()
        start_date = today - timedelta(days=days_back)
        
        # Initialize customer dates
        if not settings.customer_start_date:
            settings.customer_start_date = start_date
            print(f"✓ Set customer_start_date: {start_date}")
        else:
            print(f"✓ customer_start_date already set: {settings.customer_start_date}")
        
        if not settings.customer_end_date:
            settings.customer_end_date = today
            print(f"✓ Set customer_end_date: {today}")
        else:
            print(f"✓ customer_end_date already set: {settings.customer_end_date}")
        
        # Initialize booking dates
        if not settings.booking_start_date:
            settings.booking_start_date = start_date
            print(f"✓ Set booking_start_date: {start_date}")
        else:
            print(f"✓ booking_start_date already set: {settings.booking_start_date}")
        
        if not settings.booking_end_date:
            settings.booking_end_date = today
            print(f"✓ Set booking_end_date: {today}")
        else:
            print(f"✓ booking_end_date already set: {settings.booking_end_date}")
        
        # Save settings
        settings.save(ignore_permissions=True)
        print(f"\n✓ Settings saved successfully!\n")
        print("="*60 + "\n")
        
        return {
            "status": "success",
            "message": "Date fields initialized",
            "start_date": str(start_date),
            "end_date": str(today)
        }
        
    except Exception as e:
        print(f"\n✗ Error: {str(e)}\n")
        print("="*60 + "\n")
        return {"status": "error", "message": str(e)}


def set_custom_date_range(booking_start=None, booking_end=None, customer_start=None, customer_end=None):
    """
    Set custom date ranges for bookings and customers.
    
    Args:
        booking_start: Start date for bookings (YYYY-MM-DD format)
        booking_end: End date for bookings (YYYY-MM-DD format)
        customer_start: Start date for customers (YYYY-MM-DD format)
        customer_end: End date for customers (YYYY-MM-DD format)
    """
    print("\n" + "="*60)
    print("SETTING CUSTOM DATE RANGES")
    print("="*60 + "\n")
    
    try:
        settings = frappe.get_single("Roller Settings")
        
        if booking_start:
            settings.booking_start_date = booking_start
            print(f"✓ booking_start_date: {booking_start}")
        
        if booking_end:
            settings.booking_end_date = booking_end
            print(f"✓ booking_end_date: {booking_end}")
        
        if customer_start:
            settings.customer_start_date = customer_start
            print(f"✓ customer_start_date: {customer_start}")
        
        if customer_end:
            settings.customer_end_date = customer_end
            print(f"✓ customer_end_date: {customer_end}")
        
        settings.save(ignore_permissions=True)
        print(f"\n✓ Settings saved successfully!\n")
        print("="*60 + "\n")
        
        return {"status": "success", "message": "Date ranges set"}
        
    except Exception as e:
        print(f"\n✗ Error: {str(e)}\n")
        return {"status": "error", "message": str(e)}


# Export functions
__all__ = [
    'diagnose_settings',
    'initialize_date_fields',
    'set_custom_date_range'
]
