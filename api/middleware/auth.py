# C:\work-spaces\lead-gen\lead-gen\api\middleware\auth.py
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from uuid import uuid4

from fastapi import Request, status
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from passlib.context import CryptContext

from api.core.config import settings
from api.core.exceptions import AuthenticationError, AuthorizationError
from api.core.logging import get_structlog_logger

logger = get_structlog_logger()

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthMiddleware:
    """Authentication middleware for API routes."""
    
    def __init__(self, app, exempt_paths: Optional[list] = None):
        self.app = app
        self.exempt_paths = exempt_paths or [
            "/",
            "/health",
            "/api/health",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/auth/login",
            "/api/auth/token",
        ]
        self.exempt_patterns = [re.compile(path) for path in self.exempt_paths]
    
    async def __call__(self, request: Request, call_next):
        # Check if path is exempt from authentication
        if self._is_exempt_path(request.url.path):
            return await call_next(request)
        
        # Extract token from request
        token = self._extract_token(request)
        
        if not token:
            logger.warning("auth.missing_token", path=request.url.path, method=request.method)
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "code": "missing_token",
                    "message": "Authentication token is required",
                }
            )
        
        try:
            # Validate token
            payload = self._verify_token(token)
            
            # Check token expiration
            if self._is_token_expired(payload):
                logger.warning("auth.expired_token", path=request.url.path, user_id=payload.get("sub"))
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={
                        "code": "expired_token",
                        "message": "Token has expired",
                    }
                )
            
            # Check user status
            if not self._is_user_active(payload):
                logger.warning("auth.inactive_user", path=request.url.path, user_id=payload.get("sub"))
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={
                        "code": "inactive_user",
                        "message": "User account is inactive",
                    }
                )
            
            # Attach user info to request state
            request.state.user = {
                "id": payload.get("sub"),
                "email": payload.get("email"),
                "role": payload.get("role"),
                "buyer_id": payload.get("buyer_id"),
                "permissions": payload.get("permissions", []),
            }
            
            # Log successful authentication
            logger.debug(
                "auth.authenticated",
                user_id=payload.get("sub"),
                role=payload.get("role"),
                path=request.url.path,
            )
            
        except JWTError as e:
            logger.warning("auth.invalid_token", error=str(e), path=request.url.path)
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "code": "invalid_token",
                    "message": "Invalid authentication token",
                    "details": {"error": str(e)},
                }
            )
        except Exception as e:
            logger.error("auth.error", error=str(e), path=request.url.path)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "code": "auth_error",
                    "message": "Authentication error",
                }
            )
        
        return await call_next(request)
    
    def _is_exempt_path(self, path: str) -> bool:
        """Check if path is exempt from authentication."""
        for pattern in self.exempt_patterns:
            if pattern.fullmatch(path):
                return True
        return False
    
    def _extract_token(self, request: Request) -> Optional[str]:
        """Extract token from Authorization header."""
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return None
        
        # Support both "Bearer <token>" and "Token <token>" formats
        parts = auth_header.split()
        if len(parts) != 2:
            return None
        
        scheme, token = parts
        if scheme.lower() not in ["bearer", "token"]:
            return None
        
        return token
    
    def _verify_token(self, token: str) -> Dict:
        """Verify and decode JWT token."""
        return jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
            options={"verify_aud": False},
        )
    
    def _is_token_expired(self, payload: Dict) -> bool:
        """Check if token has expired."""
        exp = payload.get("exp")
        if not exp:
            return True
        
        expiration_time = datetime.fromtimestamp(exp)
        return datetime.utcnow() > expiration_time
    
    def _is_user_active(self, payload: Dict) -> bool:
        """Check if user account is active."""
        return payload.get("active", True)


class TokenManager:
    """Manager for JWT token operations."""
    
    @staticmethod
    def create_access_token(
        data: Dict,
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """Create a new access token."""
        to_encode = data.copy()
        
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
        
        to_encode.update({
            "exp": expire,
            "iat": datetime.utcnow(),
            "jti": str(uuid4()),
            "type": "access",
        })
        
        return jwt.encode(
            to_encode,
            settings.secret_key,
            algorithm=settings.algorithm,
        )
    
    @staticmethod
    def create_refresh_token(data: Dict) -> str:
        """Create a refresh token."""
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(days=30)
        
        to_encode.update({
            "exp": expire,
            "iat": datetime.utcnow(),
            "jti": str(uuid4()),
            "type": "refresh",
        })
        
        return jwt.encode(
            to_encode,
            settings.secret_key,
            algorithm=settings.algorithm,
        )
    
    @staticmethod
    def verify_token(token: str) -> Optional[Dict]:
        """Verify and decode a token."""
        try:
            payload = jwt.decode(
                token,
                settings.secret_key,
                algorithms=[settings.algorithm],
                options={"verify_aud": False},
            )
            return payload
        except JWTError:
            return None
    
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password."""
        return pwd_context.hash(password)
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash."""
        return pwd_context.verify(plain_password, hashed_password)


# Helper functions for route dependencies
async def get_current_user(request: Request) -> Dict:
    """Get current user from request state."""
    user = getattr(request.state, "user", None)
    if not user:
        raise AuthenticationError(message="User not authenticated")
    return user


async def require_role(request: Request, allowed_roles: list[str]) -> None:
    """Check if user has required role."""
    user = await get_current_user(request)
    
    if user.get("role") not in allowed_roles:
        raise AuthorizationError(
            message=f"Requires one of roles: {', '.join(allowed_roles)}",
            details={"user_role": user.get("role"), "allowed_roles": allowed_roles},
        )


async def require_permission(request: Request, permission: str) -> None:
    """Check if user has required permission."""
    user = await get_current_user(request)
    
    if permission not in user.get("permissions", []):
        raise AuthorizationError(
            message=f"Missing permission: {permission}",
            details={"user_permissions": user.get("permissions")},
        )

