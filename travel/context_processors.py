from .models import CardResponse


def notifications(request):
    if not request.user.is_authenticated:
        return {}
    count = CardResponse.objects.filter(
        status='rejected', item__plan__user=request.user,
    ).exclude(comment='').count()
    return {'unread_notification_count': count}
