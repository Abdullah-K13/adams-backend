from db.init import engine
from sqlalchemy import text

def fix_column():
    with engine.connect() as conn:
        try:
            # PostgreSQL syntax to drop not null constraint
            conn.execute(text("ALTER TABLE subscription_logs ALTER COLUMN subscription_id DROP NOT NULL"))
            conn.commit()
            print("Successfully altered subscription_id to be nullable")
        except Exception as e:
            print(f"Error altering column: {e}")

if __name__ == "__main__":
    fix_column()
