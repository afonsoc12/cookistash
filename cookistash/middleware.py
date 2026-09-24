from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.models import User


class AutoAdminLoginMiddleware:
    """Auto-authenticates every request as the first superuser, skipping the
    login form entirely. Intended for personal/local-only deployments where
    the host isn't reachable by anyone but the operator - gated by
    AUTO_ADMIN_LOGIN so it can be turned off if this ever gets exposed.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.AUTO_ADMIN_LOGIN and not request.user.is_authenticated:
            user = User.objects.filter(is_superuser=True).order_by("id").first()
            if user:
                login(request, user)
                request.user = user
        return self.get_response(request)
