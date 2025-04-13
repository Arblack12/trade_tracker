# trades/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from .models import UserProfile # Use relative import

# Receiver called when a User object is saved
@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    """
    Create a UserProfile when a new User is created.
    """
    if created:
        # Create the profile with the default timezone ('UTC')
        UserProfile.objects.create(user=instance)
        print(f"Created profile for user {instance.username}") # Optional: for logging
    else:
        # If user is updated, ensure profile exists (though it should)
        # and save it if needed (rarely necessary unless profile has other fields)
        try:
            instance.profile.save()
        except UserProfile.DoesNotExist:
             # If profile somehow got deleted, recreate it
             UserProfile.objects.create(user=instance)
             print(f"Re-created missing profile for user {instance.username}") # Optional