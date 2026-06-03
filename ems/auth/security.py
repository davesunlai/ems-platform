"""Hašování hesel (bcrypt) a JWT tokeny."""
from __future__ import annotations

import os
import time

import bcrypt
import jwt

JWT_SECRET = os.getenv("EMS_JWT_SECRET", "dev-insecure-change-me")
JWT_ALG = "HS256"
TOKEN_HOURS = int(os.getenv("EMS_TOKEN_HOURS", "12"))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(username: str, role: str) -> str:
    payload = {"sub": username, "role": role, "exp": int(time.time()) + TOKEN_HOURS * 3600}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
