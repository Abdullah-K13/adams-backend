from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from db.init import get_db
from models.user import Customer
from models.subscription import Invoice, SubscriptionLog
from datetime import date
import logging
from typing import Dict, Any

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/square")
async def square_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Handle Square Webhooks for Invoice Payment Failures and Successes
    """
    try:
        body_bytes = await request.body()
        data = await request.json()
        
        # Determine event type
        event_type = data.get("type")
        event_id = data.get("event_id")
        
        logger.info(f"Received Square Webhook: {event_type} - {event_id}")
        
        if event_type == "invoice.payment_failed":
            await handle_payment_failed(data, db)
        elif event_type == "invoice.payment_made": # Square calls it payment_made, not payment_succeeded for Invoices usually
             # Also check card payment success if needed, but for Subscriptions, its usually invoice related
             await handle_payment_success(data, db)
        
        return {"status": "success"}

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        # Return 200 to prevent Square from retrying indefinitely in case of logic error, but log it.
        # Check Square docs: usually 2xx is ack.
        return {"status": "error", "message": str(e)}

async def handle_payment_failed(data: Dict[str, Any], db: Session):
    try:
        object_data = data.get("data", {}).get("object", {}).get("invoice", {})
        square_customer_id = object_data.get("primary_recipient", {}).get("customer_id")
        
        if not square_customer_id:
            logger.warning("No customer ID found in payment_failed webhook")
            return

        customer = db.query(Customer).filter(Customer.square_customer_id == square_customer_id).first()
        if not customer:
            logger.warning(f"Customer not found for Square ID: {square_customer_id}")
            return

        # Increment failure count
        current_attempts = customer.failed_payment_attempts or 0
        customer.failed_payment_attempts = current_attempts + 1
        
        logger.info(f"Customer {customer.id} payment failed. Attempts: {customer.failed_payment_attempts}")

        # Suspension Rule: 3 failures
        if customer.failed_payment_attempts >= 3 and customer.subscription_status != "SUSPENDED":
            customer.subscription_status = "SUSPENDED"
            customer.subscription_active = False
            
            # Log suspension
            log = SubscriptionLog(
                customer_id=customer.id,
                subscription_id=customer.square_subscription_id,
                action="SUSPEND",
                effective_date=date.today()
            )
            db.add(log)
            logger.warning(f"Customer {customer.id} SUSPENDED due to payment failures.")

        db.commit()
    except Exception as e:
        logger.error(f"Error in handle_payment_failed: {e}")
        db.rollback()

async def handle_payment_success(data: Dict[str, Any], db: Session):
    try:
        object_data = data.get("data", {}).get("object", {}).get("invoice", {})
        square_customer_id = object_data.get("primary_recipient", {}).get("customer_id")
        
        if not square_customer_id:
             # Try getting it from payment object if invoice structure is different
             # Square structure varies by event.
             # fallback for "payment.created" or similar if needed.
             pass

        if not square_customer_id:
             logger.warning("No customer ID found in payment_made webhook")
             return

        customer = db.query(Customer).filter(Customer.square_customer_id == square_customer_id).first()
        if not customer:
            logger.warning(f"Customer not found for Square ID: {square_customer_id}")
            return

        # Reset failures on success
        if customer.failed_payment_attempts > 0:
            customer.failed_payment_attempts = 0
            logger.info(f"Customer {customer.id} payment success. Reset failures to 0.")

        # Reactivate if suspended
        if customer.subscription_status == "SUSPENDED":
            customer.subscription_status = "ACTIVE"
            customer.subscription_active = True
            
            # Log reactivation
            log = SubscriptionLog(
                customer_id=customer.id,
                subscription_id=customer.square_subscription_id,
                action="REACTIVATE",
                effective_date=date.today()
            )
            db.add(log)
            logger.info(f"Customer {customer.id} REACTIVATED after payment success.")
        
        db.commit()
    except Exception as e:
        logger.error(f"Error in handle_payment_success: {e}")
        db.rollback()
