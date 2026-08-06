import os
from app import app, db

def setup_database():
    with app.app_context():
        # This tells SQLAlchemy to look at your actual models and build the exact tables
        db.create_all()
        print("✅ Success: All database tables created to perfectly match your exact code!")

if __name__ == '__main__':
    setup_database()