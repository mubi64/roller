#!/bin/bash
# Quick test runner for local debugging

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  ROLLER BOOKING SYNC - LOCAL TESTING GUIDE                 ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}\n"

echo -e "${YELLOW}Step 1: Check Settings${NC}"
echo "  Run: bench execute roller.debug_booking_sync.check_settings"
echo "  This verifies all Roller Settings are properly configured\n"

echo -e "${YELLOW}Step 2: Test API Connection${NC}"
echo "  Run: bench execute roller.debug_booking_sync.check_api_response"
echo "  This tests connectivity and token validity\n"

echo -e "${YELLOW}Step 3: Verify Data Parsing${NC}"
echo "  Run: bench execute roller.debug_booking_sync.check_data_parsing"
echo "  This checks if data transformation works correctly\n"

echo -e "${YELLOW}Step 4: Check Database State${NC}"
echo "  Run: bench execute roller.debug_booking_sync.check_db_state"
echo "  This verifies database setup and existing data\n"

echo -e "${YELLOW}Step 5: Run Full Diagnostic${NC}"
echo "  Run: bench execute roller.test_fetch_bookings_local.run_local_test"
echo "  This runs all checks in one go\n"

echo -e "${YELLOW}Step 6: Execute Actual Sync (when ready)${NC}"
echo "  Run: bench execute roller.test_fetch_bookings_local.run_local_test --test-mode full"
echo "  Or via console: fetch_bookings_from_roller()\n"

echo -e "${GREEN}────────────────────────────────────────────────────────────${NC}\n"

echo -e "${YELLOW}Common Issues & Solutions:${NC}\n"

echo -e "${RED}Issue: 401 Unauthorized${NC}"
echo "  • Access token is expired or invalid"
echo "  • Solution: Check get_new_access_token() in roller.py"
echo "  • Check Client ID and Secret are correct\n"

echo -e "${RED}Issue: Connection Timeout${NC}"
echo "  • API server is unreachable or very slow"
echo "  • Solution: Check if base_url is correct"
echo "  • Verify network connectivity to Roller server\n"

echo -e "${RED}Issue: Empty Items Returned${NC}"
echo "  • Date range might have no bookings"
echo "  • Solution: Try expanding booking_start_date/booking_end_date"
echo "  • Check if bookings exist in Roller account for that period\n"

echo -e "${RED}Issue: Invoice Creation Fails${NC}"
echo "  • Missing default settings (Company, Customer, Address)"
echo "  • Solution: Verify default_company, default_customer, default_address exist"
echo "  • Check Sales Tax template is configured\n"

echo -e "${BLUE}For detailed error logs:${NC}"
echo "  View: Frappe > Tools > Error Log"
echo "  Search for 'Roller' to find all booking-related errors\n"

echo -e "${GREEN}────────────────────────────────────────────────────────────${NC}\n"

read -p "Start with Step 1? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    bench execute roller.debug_booking_sync.check_settings
fi
