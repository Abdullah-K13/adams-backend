from sqlalchemy.orm import Session
from db.init import get_db, engine
from models.user import Customer
from utils.square_client import get_customer_invoices
import os

def debug_invoices():
    db = next(get_db())
    # Fetch all customers with a square_customer_id
    customers = db.query(Customer).filter(Customer.square_customer_id != None).all()
    
    # Test 2: Broad Search (Check if *any* invoices exist in the account)
    print("\nTest 2: Broad Search for ANY invoices in account...")
    from utils.square_client import get_square_base_url, get_square_headers, SQUARE_LOCATION_ID
    import requests
    
    url = f"{get_square_base_url()}/v2/invoices?limit=5"
    if SQUARE_LOCATION_ID:
         url += f"&location_id={SQUARE_LOCATION_ID}"

    headers = get_square_headers()
    try:
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        
        if response.status_code == 200:
            invoices = data.get("invoices", [])
            print(f"  SUCCESS: Found {len(invoices)} total invoices in this location/account.")
            for inv in invoices:
                print(f"    - Invoice ID: {inv.get('id')}")
                print(f"      Customer ID: {inv.get('primary_recipient', {}).get('customer_id')}")
                print(f"      Amount: {inv.get('payment_requests', [{}])[0].get('computed_amount_money', {}).get('amount', 'N/A')}")
        else:
             print(f"  ERROR: API returned {response.status_code}: {data}")

    except Exception as e:
        print(f"  FATAL ERROR calling Square: {e}")

if __name__ == "__main__":
    debug_invoices()
