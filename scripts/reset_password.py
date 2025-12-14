"""
Password reset script for production use.

Usage:
    uv run python scripts/reset_password.py <username> <new_password>

Example:
    uv run python scripts/reset_password.py admin mynewpassword123
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.database import async_session_maker
from app.models import User
from app.services.auth import hash_password


async def reset_password(username: str, new_password: str):
    """Reset password for a user."""
    async with async_session_maker() as db:
        # Find user
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

        if not user:
            print(f"❌ User '{username}' not found")
            return False

        # Update password
        user.password_hash = hash_password(new_password)
        await db.commit()

        print(f"✅ Password reset successfully for user '{username}'")
        print(f"   Email: {user.email}")
        print(f"   You can now login with the new password")
        return True


async def list_users():
    """List all users in the system."""
    async with async_session_maker() as db:
        result = await db.execute(select(User))
        users = result.scalars().all()

        if not users:
            print("No users found in the database")
            return

        print("\nExisting users:")
        for user in users:
            print(f"  - {user.username} ({user.email})")


async def main():
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/reset_password.py <username> [new_password]")
        print("\nOptions:")
        print("  uv run python scripts/reset_password.py --list    List all users")
        print("  uv run python scripts/reset_password.py <username> <password>   Reset password")
        await list_users()
        sys.exit(1)

    if sys.argv[1] == "--list":
        await list_users()
        return

    if len(sys.argv) < 3:
        print("❌ Error: Password is required")
        print("Usage: uv run python scripts/reset_password.py <username> <new_password>")
        sys.exit(1)

    username = sys.argv[1]
    new_password = sys.argv[2]

    success = await reset_password(username, new_password)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
