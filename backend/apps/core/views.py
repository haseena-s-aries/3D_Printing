from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@extend_schema(responses={200: dict}, tags=["health"])
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request):
    """Liveness and database connectivity check (no tenant data)."""
    with connection.cursor() as cur:
        cur.execute("select 1")
        cur.fetchone()
    return Response({"status": "ok", "database": "ok"})
