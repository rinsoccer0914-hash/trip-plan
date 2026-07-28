from .models import CardResponse, PlanLike


def notifications(request):
    if not request.user.is_authenticated:
        return {}
    reject_count = CardResponse.objects.filter(
        status='rejected', is_read=False, item__plan__user=request.user,
    ).exclude(comment='').count()
    like_count = PlanLike.objects.filter(
        plan__user=request.user, is_read=False,
    ).exclude(user=request.user).count()
    return {'unread_notification_count': reject_count + like_count}
