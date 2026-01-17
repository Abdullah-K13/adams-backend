from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from db.init import get_db
from models.user import Customer
from models.subscription import SubscriptionPlan, Payment, PaymentMethod, SubscriptionLog
from utils.deps import get_current_user, get_db_user
from utils.square_client import (
    get_subscription_plans,
    create_square_customer,
    create_card_on_file,
    get_customer_cards,
    disable_card,
    create_subscription,
    get_subscriptions,
    cancel_subscription,
    update_subscription,
    update_subscription_card,
    pause_subscription,
    resume_subscription,
    get_customer_invoices
)
from pydantic import BaseModel
import os
import uuid
from datetime import date, datetime
import logging

logger = logging.getLogger(__name__)

class MockInvoice:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

router = APIRouter()

# --- Pydantic Models ---

class ValidateCardRequest(BaseModel):
    source_id: str
    customer_id: Optional[int] = None # Local DB ID
    # If customer_id is not provided, we might need these to create one
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None

class ActivateSubscriptionRequest(BaseModel):
    plan_variation_id: str
    customer_id: Optional[int] = None # Local DB ID
    card_id: str
    location_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    start_date: Optional[str] = None

class ChangePlanRequest(BaseModel):
    new_plan_variation_id: str

class SaveCardRequest(BaseModel):
    source_id: str

# --- Endpoints ---

@router.get("/square-config")
def get_square_config():
    return {
        "application_id": os.getenv("SQUARE_APPLICATION_ID", ""),
        "location_id": os.getenv("SQUARE_LOCATION_ID", "")
    }

@router.get("/subscription-plans")
def get_square_plans():
    """Fetch all subscription plans directly from Square Catalog."""
    result = get_subscription_plans()
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result

@router.get("/subscription-plans/db")
def get_db_plans(db: Session = Depends(get_db)):
    """Fetch all subscription plans from local database."""
    plans = db.query(SubscriptionPlan).all()
    return {"success": True, "plans": plans}

@router.post("/validate-card")
def validate_card(request: ValidateCardRequest, db: Session = Depends(get_db)):
    """
    1. Create/Get Square Customer.
    2. Attach Card to Square Customer.
    3. Return card_id and customer info.
    """
    customer = None
    if request.customer_id:
        customer = db.query(Customer).get(request.customer_id)
    
    sq_customer_id = customer.square_customer_id if customer else None
    
    if not sq_customer_id:
        # Create Square Customer
        given_name = request.given_name or (customer.first_name if customer else "Guest")
        family_name = request.family_name or (customer.last_name if customer else "User")
        email = request.email or (customer.email if customer else f"guest_{uuid.uuid4().hex[:8]}@example.com")
        
        res = create_square_customer(
            given_name=given_name,
            family_name=family_name,
            email=email,
            phone_number=request.phone_number or (customer.phone_number if customer else None)
        )
        
        if not res.get("success"):
            raise HTTPException(status_code=400, detail=f"Square customer creation failed: {res.get('error')}")
        sq_customer_id = res.get("customer_id")
        
        if customer:
            customer.square_customer_id = sq_customer_id
            db.commit()

    # Attach Card
    card_res = create_card_on_file(
        source_id=request.source_id,
        customer_id=sq_customer_id
    )
    
    if not card_res.get("success"):
        raise HTTPException(status_code=400, detail=f"Card validation failed: {card_res.get('error')}")

    # Save Payment Method to DB if customer exists
    if customer:
        new_method = PaymentMethod(
            customer_id=customer.id,
            square_card_id=card_res.get("card_id"),
            last_4_digits=card_res.get("last_4"),
            card_brand=card_res.get("brand"),
            exp_month=card_res.get("exp_month"),
            exp_year=card_res.get("exp_year"),
            is_default=True
        )
        # Set others to not default
        db.query(PaymentMethod).filter(PaymentMethod.customer_id == customer.id).update({"is_default": False})
        db.add(new_method)
        db.commit()

    return {
        "success": True,
        "card_id": card_res.get("card_id"),
        "customer_id": sq_customer_id,
        "card_details": card_res
    }

@router.get("/my-cards")
def get_my_cards(user: Customer = Depends(get_db_user), db: Session = Depends(get_db)):
    """Fetch saved payment methods for the authenticated customer."""
    if not user.square_customer_id:
        return {"success": True, "cards": []}
    
    # 1. Fetch from local DB
    db_methods = db.query(PaymentMethod).filter(PaymentMethod.customer_id == user.id).all()
    db_card_map = {pm.square_card_id: pm for pm in db_methods}
    
    # 2. Fetch from Square to ensure sync
    sq_res = get_customer_cards(user.square_customer_id)
    sq_cards = sq_res.get("cards", []) if sq_res.get("success") else []
    
    # 3. Merge: Start with Square cards and enrich with DB info if available
    final_cards = []
    sq_card_ids_in_list = set()
    
    for sq_c in sq_cards:
        card_id = sq_c.get("id")
        sq_card_ids_in_list.add(card_id)
        
        db_pm = db_card_map.get(card_id)
        
        final_cards.append({
            "id": card_id,
            "last_4": sq_c.get("last_4") or (db_pm.last_4_digits if db_pm else ""),
            "brand": sq_c.get("card_brand") or (db_pm.card_brand if db_pm else "Unknown"),
            "exp_month": sq_c.get("exp_month") or (db_pm.exp_month if db_pm else 0),
            "exp_year": sq_c.get("exp_year") or (db_pm.exp_year if db_pm else 0),
            "is_default": db_pm.is_default if db_pm else False,
            "is_active_in_square": True
        })
    
    # Also add any cards from DB that might not have been in Square response (though unlikely if sq sync is on)
    for card_id, pm in db_card_map.items():
        if card_id not in sq_card_ids_in_list:
            final_cards.append({
                "id": pm.square_card_id,
                "last_4": pm.last_4_digits,
                "brand": pm.card_brand,
                "exp_month": pm.exp_month,
                "exp_year": pm.exp_year,
                "is_default": pm.is_default,
                "is_active_in_square": False
            })
    
    return {
        "success": True,
        "cards": final_cards
    }

@router.post("/save-card")
def save_card(request: SaveCardRequest, user: Customer = Depends(get_db_user), db: Session = Depends(get_db)):
    """
    Save a new payment method for the logged-in customer.
    If they have an active subscription, update it to use this new card.
    """
    if not user.square_customer_id:
        # Should ideally have one by now if they reached dashboard, but let's be safe
        res = create_square_customer(
            given_name=user.first_name,
            family_name=user.last_name,
            email=user.email,
            phone_number=user.phone_number
        )
        if not res.get("success"):
            raise HTTPException(status_code=400, detail=f"Failed to create Square customer: {res.get('error')}")
        user.square_customer_id = res.get("customer_id")
        db.commit()

    # 1. Create Card in Square
    card_res = create_card_on_file(
        source_id=request.source_id,
        customer_id=user.square_customer_id
    )
    
    if not card_res.get("success"):
        raise HTTPException(status_code=400, detail=f"Failed to save card: {card_res.get('error')}")
        
    card_id = card_res.get("card_id")
    
    # 2. Save to Local DB
    # Disable previous default
    db.query(PaymentMethod).filter(PaymentMethod.customer_id == user.id).update({"is_default": False})
    
    new_method = PaymentMethod(
        customer_id=user.id,
        square_card_id=card_id,
        last_4_digits=card_res.get("last_4"),
        card_brand=card_res.get("brand"),
        exp_month=card_res.get("exp_month"),
        exp_year=card_res.get("exp_year"),
        is_default=True
    )
    db.add(new_method)
    
    # 3. Update active subscription if exists
    if user.square_subscription_id and user.subscription_active:
        logger.info(f"Updating subscription {user.square_subscription_id} to use new card {card_id}")
        update_subscription_card(user.square_subscription_id, card_id)
    
    db.commit()
    
    return {
        "success": True,
        "message": "Payment method saved successfully",
        "card_id": card_id
    }

@router.delete("/remove-card/{card_id}")
def remove_card(card_id: str, user: Customer = Depends(get_db_user), db: Session = Depends(get_db)):
    """Disable a card in Square and remove from local DB."""
    # 1. Disable in Square
    disable_card(card_id)
    
    # 2. Remove from Local DB (or mark as inactive)
    method = db.query(PaymentMethod).filter(
        PaymentMethod.customer_id == user.id,
        PaymentMethod.square_card_id == card_id
    ).first()
    
    if method:
        db.delete(method)
        db.commit()
        
    return {"success": True, "message": "Card removed successfully"}

def dummy_create_subscription(customer_id: str, location_id: str, plan_variation_id: str, card_id: str, **kwargs) -> Dict[str, Any]:
    """Helper for testing to skip real Square call, matching Skeeter project logic."""
    return {
        "success": True,
        "subscription_id": f"dummy_sub_{uuid.uuid4().hex[:12]}",
        "subscription": {"status": "ACTIVE", "id": f"dummy_sub_{uuid.uuid4().hex[:12]}"}
    }

@router.post("/activate-subscription")
def activate_sub(request: ActivateSubscriptionRequest, db: Session = Depends(get_db)):
    customer = None
    if request.customer_id:
        customer = db.query(Customer).get(request.customer_id)
    
    sq_customer_id = customer.square_customer_id if customer else None
    if not sq_customer_id:
        raise HTTPException(status_code=400, detail="Square customer ID missing")

    location_id = request.location_id or os.getenv("SQUARE_LOCATION_ID")
    
    # Create subscription using dummy function to match Skeeter logic
    res = dummy_create_subscription(
        customer_id=sq_customer_id,
        location_id=location_id,
        plan_variation_id=request.plan_variation_id,
        card_id=request.card_id,
        idempotency_key=request.idempotency_key
    )
    
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=f"Subscription failed: {res.get('error')}")

    if customer:
        customer.square_subscription_id = res.get("subscription_id")
        customer.subscription_active = True
        customer.subscription_status = "ACTIVE"
        db.commit()
        
        # Log payment locally
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.plan_variation_id == request.plan_variation_id).first()
        if plan:
            new_payment = Payment(
                customer_id=customer.id,
                amount=plan.plan_cost,
                status="PAID",
                square_transaction_id=res.get("subscription_id")
            )
            db.add(new_payment)

        # Log action
        log = SubscriptionLog(
            customer_id=customer.id,
            subscription_id=res.get("subscription_id"),
            action="ACTIVATE",
            effective_date=date.today()
        )
        db.add(log)
        db.commit()

    return res

@router.get("/my-subscriptions")
def get_my_subs(user: Customer = Depends(get_db_user)):
    if not user.square_customer_id:
        return {"success": True, "subscriptions": []}
    
    # Fetch user's subscriptions
    subs_res = get_subscriptions(customer_id=user.square_customer_id)
    if not subs_res.get("success"):
        return subs_res
        
    subscriptions = subs_res.get("subscriptions", [])
    
    # Fetch all plans to map names and amounts
    plans_res = get_subscription_plans()
    plans_map = {}
    if plans_res.get("success"):
        for p in plans_res.get("plans", []):
            for v in p.get("variations", []):
                # Try to get price from the first phase
                price = 0
                if v.get("phases") and len(v["phases"]) > 0:
                    price = int(v["phases"][0].get("recurring_price_money", {}).get("amount", 0))
                
                plans_map[v["id"]] = {
                    "name": f"{p['name']} - {v['name']}",
                    "amount": price
                }
    
    # Enrich subscriptions
    enriched_subs = []
    for sub in subscriptions:
        # Create a copy to modify
        s = sub.copy()
        var_id = s.get("plan_variation_id")
        
        # Map fields
        if var_id in plans_map:
            s["plan_name"] = plans_map[var_id]["name"]
            s["amount"] = plans_map[var_id]["amount"]
        else:
            s["plan_name"] = "Unknown Plan"
            s["amount"] = 0
            
        # Map next_billing_date from charged_through_date
        s["next_billing_date"] = s.get("charged_through_date")
        
        enriched_subs.append(s)
        
    return {"success": True, "subscriptions": enriched_subs}

@router.post("/pause-subscription")
def pause_sub(user: Customer = Depends(get_db_user), db: Session = Depends(get_db)):
    if not user.square_subscription_id:
        raise HTTPException(status_code=404, detail="No active subscription found")
    
    res = pause_subscription(user.square_subscription_id)
    if "errors" in res:
        raise HTTPException(status_code=400, detail=str(res["errors"]))
    
    user.subscription_status = "PAUSED"
    log = SubscriptionLog(
        customer_id=user.id,
        subscription_id=user.square_subscription_id,
        action="PAUSE",
        effective_date=date.today()
    )
    db.add(log)
    db.commit()
    return res

@router.post("/resume-subscription")
def resume_sub(user: Customer = Depends(get_db_user), db: Session = Depends(get_db)):
    if not user.square_subscription_id:
        raise HTTPException(status_code=404, detail="No active subscription found")
    
    res = resume_subscription(user.square_subscription_id)
    if "errors" in res:
        raise HTTPException(status_code=400, detail=str(res["errors"]))
    
    user.subscription_status = "ACTIVE"
    log = SubscriptionLog(
        customer_id=user.id,
        subscription_id=user.square_subscription_id,
        action="RESUME",
        effective_date=date.today()
    )
    db.add(log)
    db.commit()
    return res

@router.post("/cancel-subscription")
def cancel_sub(user: Customer = Depends(get_db_user), db: Session = Depends(get_db)):
    if not user.square_subscription_id:
        raise HTTPException(status_code=404, detail="No active subscription found")
    
    res = cancel_subscription(user.square_subscription_id)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    
    user.subscription_active = False
    user.subscription_status = "CANCELED"
    log = SubscriptionLog(
        customer_id=user.id,
        subscription_id=user.square_subscription_id,
        action="CANCEL",
        effective_date=date.today()
    )
    db.add(log)
    db.commit()
    return res

@router.post("/change-plan")
def change_plan(request: ChangePlanRequest, user: Customer = Depends(get_db_user), db: Session = Depends(get_db)):
    if not user.square_subscription_id:
        raise HTTPException(status_code=404, detail="No active subscription found")
    
    res = update_subscription(user.square_subscription_id, request.new_plan_variation_id)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    
    return res

@router.get("/billing-history")
def billing_history(user: Customer = Depends(get_db_user)):
    if not user.square_customer_id:
        return {"success": True, "invoices": []}
    
    res = get_customer_invoices(user.square_customer_id)
    if not res.get("success"):
        return res
        
    invoices = res.get("invoices", [])
    enriched_invoices = []
    
    for inv in invoices:
        i = inv.copy()
        
        amount = 0
        if "payment_requests" in i and i["payment_requests"]:
            for req in i["payment_requests"]:
                 amount += int(req.get("computed_amount_money", {}).get("amount", 0))
        
        i["amount"] = amount / 100.0 # Convert to dollars
        i["description"] = i.get("title") or i.get("description") or "Subscription Payment"
        i["created_at"] = i.get("invoice_date") or i.get("scheduled_at") or i.get("created_at")
             
        enriched_invoices.append(i)
        
    return {"success": True, "invoices": enriched_invoices}

@router.get("/my-invoice-pdf/{square_invoice_id}")
def download_my_invoice_pdf(
    square_invoice_id: str,
    db: Session = Depends(get_db),
    user: Customer = Depends(get_db_user)
):
    from models.subscription import Invoice, SubscriptionPlan
    from utils.pdf_generator import generate_invoice_pdf
    
    # Check local DB first
    invoice = db.query(Invoice).filter(Invoice.square_invoice_id == square_invoice_id).first()
    
    if not invoice:
        # If not in local DB, fetch from Square to support live testing for existing customers
        res = get_customer_invoices(user.square_customer_id)
        if not res.get("success"):
            raise HTTPException(status_code=404, detail="Invoice not found")
        
        sq_inv = next((inv for inv in res.get("invoices", []) if inv.get("id") == square_invoice_id), None)
        if not sq_inv:
            raise HTTPException(status_code=404, detail="Invoice not found in Square")
        
        # Calculate amount from payment requests
        amount = 0
        if sq_inv.get("payment_requests"):
            amount = int(sq_inv.get("payment_requests")[0].get("computed_amount_money", {}).get("amount", 0)) / 100.0
        
        # Parse dates safely
        created_at_str = sq_inv.get("created_at")
        due_date_str = sq_inv.get("scheduled_at") or created_at_str
        
        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            due_date = datetime.fromisoformat(due_date_str.replace("Z", "+00:00")).date()
        except:
            created_at = datetime.now()
            due_date = created_at.date()

        # Create mock object for the PDF generator
        invoice = MockInvoice(
            square_invoice_id=sq_inv.get("id"),
            amount=amount,
            status=sq_inv.get("status"),
            created_at=created_at,
            due_date=due_date
        )

    # Validate ownership
    if getattr(invoice, 'customer_id', user.id) != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get plan name
    plan_name = "Subscription Service"
    if user.plan_id:
        try:
            # Plan ID might be stored as string or int, handle carefully
            plan_id_int = int(user.plan_id) if str(user.plan_id).isdigit() else 0
            plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id_int).first()
            if plan:
                plan_name = plan.plan_name
        except:
            pass
            
    return generate_invoice_pdf(invoice, user, plan_name)
