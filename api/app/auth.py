"""Cognito JWT verification for FastAPI.

Verifies the id_token minted by the Cognito hosted UI (Google sign-in). The token
signature is checked against the pool's JWKS; issuer, audience and token_use are
validated. Returns the authenticated user on success.
"""
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.settings import settings

_bearer = HTTPBearer(auto_error=False)


class AuthUser(BaseModel):
    sub: str
    email: str
    name: str | None = None


@lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    issuer = (
        f"https://cognito-idp.{settings.aws_region}.amazonaws.com/"
        f"{settings.cognito_user_pool_id}"
    )
    return jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json")


def _issuer() -> str:
    return (
        f"https://cognito-idp.{settings.aws_region}.amazonaws.com/"
        f"{settings.cognito_user_pool_id}"
    )


def require_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    if creds is None or not creds.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = creds.credentials
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.cognito_client_id,
            issuer=_issuer(),
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc

    if claims.get("token_use") != "id":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Expected an id token")
    email = claims.get("email")
    if not email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing email")

    return AuthUser(sub=claims["sub"], email=email, name=claims.get("name"))
