from sqlalchemy.orm import Session
from db.init import SessionLocal
from models.subscription import SubscriptionPlan

def seed_plans():
    db = SessionLocal()
    try:
        # Check if plans already exist
        existing_plans = db.query(SubscriptionPlan).count()
        if existing_plans > 0:
            print(f"Database already has {existing_plans} plans. Skipping seeding.")
            return

        plans = [
            SubscriptionPlan(
                plan_name="Basic Care Plan",
                plan_cost=29.99,
                plan_variation_id="BASIC_MONTHLY_PH",
                plan_description="Essential property care covering basic lawn maintenance and seasonal cleanup."
            ),
            SubscriptionPlan(
                plan_name="Standard Care Plan",
                plan_cost=49.99,
                plan_variation_id="STANDARD_MONTHLY_PH",
                plan_description="Most popular! Includes everything in Basic plus weed control and fertilization."
            ),
            SubscriptionPlan(
                plan_name="Premium Care Plan",
                plan_cost=79.99,
                plan_variation_id="PREMIUM_MONTHLY_PH",
                plan_description="Total property management including aeration, pest control, and priority scheduling."
            )
        ]

        db.add_all(plans)
        db.commit()
        print("Successfully seeded 3 basic subscription plans.")
    except Exception as e:
        print(f"Error seeding plans: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_plans()
