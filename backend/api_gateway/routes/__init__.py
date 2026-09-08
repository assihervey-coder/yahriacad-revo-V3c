"""Routers REST /api/v1/*"""
from api_gateway.routes.billing import router as billing_router
from api_gateway.routes.chat import router as chat_router
from api_gateway.routes.components import router as components_router
from api_gateway.routes.designs import router as designs_router
from api_gateway.routes.exports import router as exports_router
from api_gateway.routes.optimization import router as optimization_router
from api_gateway.routes.projects import router as projects_router
from api_gateway.routes.simulations import router as simulations_router

__all__ = [
    "billing_router", "chat_router", "components_router", "designs_router",
    "exports_router", "optimization_router", "projects_router", "simulations_router",
]
