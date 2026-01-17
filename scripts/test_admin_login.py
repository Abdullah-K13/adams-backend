"""
Test script to verify admin login credentials
"""
import sys
import os

# Add the parent directory to sys.path to allow importing from backend modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from db.init import SessionLocal
from models.user import Admin
from utils.security import verify_password, hash_password

def test_admin_login():
    email = "admin@adamspropertycare.com"
    password = "admin123"
    
    db = SessionLocal()
    try:
        admin = db.query(Admin).filter(Admin.email == email).first()
        
        if not admin:
            print(f"[ERROR] Admin with email {email} not found in database")
            print("\nAvailable admins in database:")
            all_admins = db.query(Admin).all()
            if all_admins:
                for a in all_admins:
                    print(f"  - {a.email} (ID: {a.id}, Name: {a.name})")
            else:
                print("  No admins found in database")
            return False
        
        print(f"[OK] Admin found: {admin.email}")
        print(f"  Name: {admin.name}")
        print(f"  ID: {admin.id}")
        print(f"  Password hash: {admin.password_hash[:50]}...")
        
        # Test password verification
        print(f"\nTesting password verification...")
        print(f"  Input password: {password}")
        print(f"  Stored hash: {admin.password_hash[:50]}...")
        
        is_valid = verify_password(password, admin.password_hash)
        
        if is_valid:
            print("[OK] Password verification: SUCCESS")
            return True
        else:
            print("[ERROR] Password verification: FAILED")
            print("\nThe password hash might be incorrect.")
            print("Try recreating the admin with:")
            print("  python scripts/create_admin.py")
            return False
            
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    test_admin_login()
