"""Create initial admin user and invitation code.

Usage:
  python seed_user.py

Creates:
  - Admin user: goldman424@gmail.com / yachida0024
  - Default UserSettings for the admin
"""
import asyncio
from app.database import engine, async_session, Base
from app.models.user import User
from app.models.settings import UserSettings
from app.core.auth import hash_password
from sqlalchemy import select


async def seed():
    # Create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as db:
        # Check if user already exists
        result = await db.execute(select(User).where(User.email == "goldman424@gmail.com"))
        existing = result.scalar_one_or_none()
        if existing:
            print(f"User already exists: {existing.email} (id: {existing.id})")
            return

        # Create admin user
        user = User(
            email="goldman424@gmail.com",
            password_hash=hash_password("yachida0024"),
            display_name="YACHI",
            is_active=True,
        )
        db.add(user)
        await db.flush()

        # Create default settings
        db.add(UserSettings(user_id=user.id))

        await db.commit()
        print(f"Created user: {user.email} (id: {user.id})")
        print("Login: goldman424@gmail.com / yachida0024")


if __name__ == "__main__":
    asyncio.run(seed())
