import requests
import json

BASE_URL = "http://localhost:8000"
WEBHOOK_URL = f"{BASE_URL}/webhooks/square"

# Mock Data
# You might need to update this with a real customer ID from your database if 'fake_customer' doesn't exist
# Or ensure the backend logic handles 'not found' gracefully (which it does)
# Ideally, we should create a test customer first or use an existing one.
# Let's assume we use a dummy ID and mock the DB lookup if we were writing a unit test, 
# but for integration test against running server, we need a real ID.
# I will use a placeholder and print instruction to user to update it if needed, 
# or query the API first to get a customer.

def get_test_customer():
    # Try to login or list customers to find one. 
    # For simplicity, let's assume we can pick the first one from the database using a script or just try to hit the endpoint.
    # Actually, let's just use a hardcoded predictable ID if we can, or ask backend to create one.
    # Since I don't have a clean way to get a customer ID via script without auth, I'll rely on the user to check logs.
    # But wait, I can write a python script that imports DB session.
    pass

if __name__ == "__main__":
    from db.init import SessionLocal
    from models.user import Customer
    import time

    db = SessionLocal()
    # Find a test customer or create one
    test_email = "webhook_test@example.com"
    customer = db.query(Customer).filter(Customer.email == test_email).first()
    
    if not customer:
        print("Creating test customer...")
        customer = Customer(
            email=test_email,
            first_name="Webhook",
            last_name="Test",
            square_customer_id="sq_test_123", # Mock ID
            square_subscription_id="sub_test_456", # Mock Sub ID
            subscription_status="ACTIVE",
            failed_payment_attempts=0
        )
        db.add(customer)
        db.commit()
    else:
        # Reset state
        customer.failed_payment_attempts = 0
        customer.subscription_status = "ACTIVE"
        customer.subscription_active = True
        db.commit()
    
    customer_sq_id = customer.square_customer_id
    print(f"Testing with Customer: {customer.email} (Square ID: {customer_sq_id})")

    # 1. Simulate 3 Failures
    print("\n--- Simulating 3 Payment Failures ---")
    payload = {
        "type": "invoice.payment_failed",
        "event_id": "test_event_1",
        "data": {
            "object": {
                "invoice": {
                    "primary_recipient": {
                        "customer_id": customer_sq_id
                    }
                }
            }
        }
    }

    for i in range(3):
        print(f"Sending Failure #{i+1}...")
        try:
            res = requests.post(WEBHOOK_URL, json=payload)
            print(f"Response: {res.status_code} {res.json()}")
        except Exception as e:
             print(f"Request failed (is server running?): {e}")
        time.sleep(1)

    # Check status
    db.refresh(customer)
    print(f"Current Attempts: {customer.failed_payment_attempts}")
    print(f"Current Status: {customer.subscription_status}")
    
    if customer.subscription_status == "SUSPENDED":
        print("SUCCESS: Customer is SUSPENDED.")
    else:
        print("FAILURE: Customer is NOT SUSPENDED.")

    # 2. Simulate Success
    print("\n--- Simulating Payment Success ---")
    payload_success = {
        "type": "invoice.payment_made",
        "event_id": "test_event_success",
        "data": {
            "object": {
                "invoice": {
                    "primary_recipient": {
                        "customer_id": customer_sq_id
                    }
                }
            }
        }
    }
    
    try:
        res = requests.post(WEBHOOK_URL, json=payload_success)
        print(f"Response: {res.status_code} {res.json()}")
    except Exception as e:
         print(f"Request failed: {e}")

    # Check status
    db.refresh(customer)
    print(f"Current Attempts: {customer.failed_payment_attempts}")
    print(f"Current Status: {customer.subscription_status}")

    if customer.subscription_status == "ACTIVE" and customer.failed_payment_attempts == 0:
        print("SUCCESS: Customer is REACTIVATED.")
    else:
        print("FAILURE: Customer is NOT REACTIVATED.")
    
    # Cleanup
    # db.delete(customer)
    # db.commit()
    db.close()
