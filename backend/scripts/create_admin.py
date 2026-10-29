"""Create (or promote) an administrator account.

    python -m scripts.create_admin you@example.org "Your Name"        # prompts for the password
    ADMIN_PASSWORD=... python -m scripts.create_admin you@example.org "Your Name"

Administrators cannot sign themselves up; this command and POST /api/v1/admin/users
are the only ways to create one.
"""

import asyncio
import getpass
import os
import sys

from sqlalchemy import select

from app.core.auth import hash_password
from app.db.session import AsyncSessionLocal
from app.models.user import User


async def main(email: str, name: str, password: str) -> None:
    email = email.strip().lower()
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            session.add(User(email=email, name=name, password_hash=await hash_password(password), role="admin"))
            print(f"created administrator {email}")
        else:
            user.role = "admin"
            user.active = True
            user.password_hash = await hash_password(password)
            print(f"updated {email}: now an administrator with the new password")
        await session.commit()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    pw = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password (min 8 characters): ")
    if len(pw) < 8:
        sys.exit("password must be at least 8 characters")
    asyncio.run(main(sys.argv[1], sys.argv[2], pw))
