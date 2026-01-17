"""
List all admin users in the database
"""
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from db.init import SessionLocal
from models.user import Admin

def list_admins():
    db = SessionLocal()
    try:
        admins = db.query(Admin).all()
        if not admins:
            print("No admins found in database")
            return
        
        print(f"Found {len(admins)} admin(s):")
        for admin in admins:
            print(f"  - Email: {admin.email}")
            print(f"    Name: {admin.name}")
            print(f"    ID: {admin.id}")
            print()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    list_admins()
