# trades/middleware.py
from django.utils import timezone
import pytz
from .models import UserProfile # Use relative import

class TimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user_tz_name = None
        # Check if user is authenticated and not anonymous
        if hasattr(request, 'user') and request.user.is_authenticated:
            try:
                # Try to get the profile and the timezone setting
                # Use select_related to fetch user and profile in one query if needed elsewhere
                profile = UserProfile.objects.get(user=request.user)
                user_tz_name = profile.time_zone
            except UserProfile.DoesNotExist:
                # Profile doesn't exist? Signal should prevent this for saved users.
                # Could happen during signup process before profile save?
                # Or if profile was manually deleted.
                # Create one now with default UTC.
                profile = UserProfile.objects.create(user=request.user, time_zone='UTC')
                user_tz_name = profile.time_zone
                print(f"WARNING: Created missing profile for user {request.user.username} in middleware.") # Log this

        # Activate the timezone if we found a valid one
        if user_tz_name:
            try:
                timezone.activate(user_tz_name)
            except pytz.exceptions.UnknownTimeZoneError:
                # Stored timezone is invalid? Fallback to default UTC
                print(f"WARNING: Invalid timezone '{user_tz_name}' found for user {request.user.username}. Using UTC.")
                timezone.deactivate() # Deactivate to use settings.TIME_ZONE (UTC)
        else:
            # Anonymous user or user with no timezone preference yet, use default
            timezone.deactivate() # Deactivate to use settings.TIME_ZONE (UTC)

        # Process the request with the activated timezone
        response = self.get_response(request)

        # Deactivate timezone after processing response (good practice)
        timezone.deactivate()

        return response