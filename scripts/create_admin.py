import sys
import os

# Add the parent directory to sys.path to allow importing from backend modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from db.init import SessionLocal
from models.user import Admin
from utils.security import hash_password

def create_admin():
    email = "admin@adamspropertycare.com"
    password = "admin123"
    name = "Adams Admin"
    
    db = SessionLocal()
    try:
        # Check if already exists
        existing = db.query(Admin).filter(Admin.email == email).first()
        if existing:
            print(f"Admin with email {email} already exists.")
            return

        hashed = hash_password(password)
        new_admin = Admin(
            name=name,
            email=email,
            password_hash=hashed,
            phone_number="555-0100"
        )
        db.add(new_admin)
        db.commit()
        print(f"Admin user {email} created successfully.")
    except Exception as e:
        print(f"Error creating admin: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    create_admin()
