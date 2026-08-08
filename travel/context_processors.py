from .models import CardResponse, EditRequest, PlanLike, ScheduleItem


def notifications(request):
    if not request.user.is_authenticated:
        return {}
    response_count = CardResponse.objects.filter(
        is_read=False, item__plan__user=request.user,
    ).exclude(user=request.user).count()
    like_count = PlanLike.objects.filter(
        plan__user=request.user, is_read=False,
    ).exclude(user=request.user).count()
    pending_approval_count = (
        ScheduleItem.objects.filter(approval_enabled=True, plan__group__members=request.user)
        .exclude(plan__user=request.user)
        .exclude(responses__user=request.user)
        .count()
    )
    edit_decision_count = EditRequest.objects.filter(
        user=request.user, is_read=False,
    ).exclude(status='pending').count()
    pending_edit_request_count = EditRequest.objects.filter(
        status='pending', plan__user=request.user,
    ).count()
    return {
        'unread_notification_count': (
            response_count + like_count + pending_approval_count
            + edit_decision_count + pending_edit_request_count
        ),
    }
