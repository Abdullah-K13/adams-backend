from db.init import engine
from sqlalchemy import text

def add_column():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE customers ADD COLUMN failed_payment_attempts INTEGER DEFAULT 0"))
            conn.commit()
            print("Successfully added failed_payment_attempts column")
        except Exception as e:
            print(f"Error (column might already exist): {e}")

if __name__ == "__main__":
    add_column()
