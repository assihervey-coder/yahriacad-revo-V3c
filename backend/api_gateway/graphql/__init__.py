"""GraphQL — schema strawberry (ou repli JSON) + router."""
from api_gateway.graphql.schema import HAS_STRAWBERRY, execute_query, router

__all__ = ["router", "execute_query", "HAS_STRAWBERRY"]
