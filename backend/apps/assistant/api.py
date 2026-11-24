"""POST /api/v1/assistant/: one question in, one answer out. Any signed-in member may ask; what the answer contains is
limited by apps.assistant.lookups to what the person can open on the screens. Nothing is stored and no external
service is called."""
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .engine import reply, suggestions
from .lookups import scope_of

_ITEM = inline_serializer("AssistantItem", {"title": serializers.CharField(), "subtitle": serializers.CharField(),
                                            "link": serializers.CharField(allow_null=True)})
_ANSWER = inline_serializer("AssistantAnswer", {
    "answer": serializers.CharField(), "items": _ITEM.__class__(many=True),
    "links": serializers.ListField(child=serializers.DictField()), "suggestions": serializers.ListField(child=serializers.CharField())})


class AssistantView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "assistant"

    @extend_schema(tags=["assistant"], responses={200: inline_serializer("AssistantStart", {
        "suggestions": serializers.ListField(child=serializers.CharField()), "full_access": serializers.BooleanField()})})
    def get(self, request):
        """Opening the assistant: suggested questions for this person's role."""
        scope = scope_of(request)
        return Response({"suggestions": suggestions(scope), "full_access": scope.full})

    @extend_schema(tags=["assistant"], request=inline_serializer("AssistantQuestion", {
        "message": serializers.CharField(max_length=500), "context": serializers.DictField(required=False)}), responses={200: _ANSWER})
    def post(self, request):
        message = str(request.data.get("message") or "")[:500]
        context = request.data.get("context") if isinstance(request.data.get("context"), dict) else {}
        return Response(reply(request, message, context))
