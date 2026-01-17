from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from db.init import get_db
from models.user import Customer, Admin
from models.subscription import SubscriptionPlan
from utils.security import hash_password, verify_password, create_access_token
from typing import Optional
from pydantic import BaseModel, EmailStr

router = APIRouter()

class SignupRequest(BaseModel):
    firstName: str
    lastName: str
    email: EmailStr
    phone: str
    password: str
    address: str
    city: str
    zip: str
    plan: Optional[str] = None
    planVariationId: Optional[str] = None
    referralNumber: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

@router.post("/signup")
def signup(request: SignupRequest, db: Session = Depends(get_db)):
    # Check if user exists
    existing_user = db.query(Customer).filter(Customer.email == request.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Use the hash_password utility from security.py
    hashed_password = hash_password(request.password) 
    
    new_user = Customer(
        first_name=request.firstName,
        last_name=request.lastName,
        email=request.email,
        phone_number=request.phone,
        password_hash=hashed_password,
        address=request.address,
        city=request.city,
        zip_code=request.zip,
        plan_id=request.plan,
        plan_variation_id=request.planVariationId,
        referral_number=request.referralNumber,
        subscription_active=False,
        subscription_status="PENDING"
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # Create simple access token
    access_token = f"token_{new_user.id}"
    
    # Get plan details safely
    plan_obj = None
    if new_user.plan_id and str(new_user.plan_id).isdigit():
        plan_obj = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == int(new_user.plan_id)).first()

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": new_user.id,
        "user": {
            "id": new_user.id,
            "email": new_user.email,
            "firstName": new_user.first_name,
            "lastName": new_user.last_name,
            "role": "customer",
            "plan_id": new_user.plan_id,
            "plan_name": plan_obj.plan_name if plan_obj else "Active Plan",
            "plan_cost": plan_obj.plan_cost if plan_obj else 0,
            "subscription_status": new_user.subscription_status
        }
    }

@router.post("/login")
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(Customer).filter(Customer.email == request.email).first()
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    access_token = create_access_token(data={"sub": user.email, "id": user.id})
    
    plan_obj = None
    if user.plan_id and str(user.plan_id).isdigit():
        plan_obj = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == int(user.plan_id)).first()

    return {"access_token": access_token, "token_type": "bearer", "user": {
        "id": user.id,
        "email": user.email,
        "firstName": user.first_name,
        "lastName": user.last_name,
        "role": "customer",
        "plan_id": user.plan_id,
        "plan_name": plan_obj.plan_name if plan_obj else "Active Plan",
        "plan_cost": plan_obj.plan_cost if plan_obj else 0,
        "subscription_status": user.subscription_status
    }}

@router.post("/admin/login")
def admin_login(request: LoginRequest, db: Session = Depends(get_db)):
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"Admin login attempt for email: {request.email}")
    
    admin = db.query(Admin).filter(Admin.email == request.email).first()
    
    if not admin:
        logger.warning(f"Admin not found for email: {request.email}")
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    logger.info(f"Admin found: {admin.email}, verifying password...")
    password_valid = verify_password(request.password, admin.password_hash)
    
    if not password_valid:
        logger.warning(f"Password verification failed for email: {request.email}")
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    logger.info(f"Login successful for admin: {admin.email}")
    access_token = create_access_token(data={"sub": admin.email, "id": admin.id, "role": "admin"})
    return {"access_token": access_token, "token_type": "bearer", "user": {
        "id": admin.id,
        "email": admin.email,
        "name": admin.name,
        "role": "admin"
    }}
