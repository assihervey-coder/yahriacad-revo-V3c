"""GraphQL — schema strawberry (ou repli JSON) + router."""
from api_gateway.graphql.schema import router, execute_query, HAS_STRAWBERRY

__all__ = ["router", "execute_query", "HAS_STRAWBERRY"]
