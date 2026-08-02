import json
from datetime import datetime, time, timedelta
from urllib.parse import urlencode
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.db.models import Q, Case, When, Value, IntegerField
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse, Http404
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from .models import TravelPlan, CardTemplate, ScheduleItem, Group, CardResponse, GroupMessage, PlanLike, Profile

DEFAULT_CARDS = [
    ('起床・就寝', 'wake'),
    ('移動', 'move'),
    ('ご飯', 'eat'),
    ('観光', 'see'),
    ('ホテル', 'stay'),
    ('その他', 'other'),
    ('予備時間', 'free'),
]

# card_type -> subtype labels the add-modal offers as a dropdown; the chosen
# label becomes the schedule item's name (overriding the template's own name).
SUBTYPE_CHOICES = {
    'wake': ['起床', '就寝'],
    'move': ['車', '電車', 'バス', '飛行機', '徒歩', '自転車'],
    'eat': ['朝食', '昼食', '夕食'],
    'stay': ['チェックイン', 'チェックアウト'],
}

# Display order for card types in the card palette / management list.
CARD_TYPE_ORDER = ['wake', 'move', 'eat', 'see', 'stay', 'free', 'other']


def _ordered_templates(user):
    order_case = Case(
        *[When(card_type=t, then=Value(i)) for i, t in enumerate(CARD_TYPE_ORDER)],
        default=Value(len(CARD_TYPE_ORDER)),
        output_field=IntegerField(),
    )
    return CardTemplate.objects.filter(user=user).annotate(_type_order=order_case).order_by('is_default', '_type_order', 'name')

WEEKDAY_JA = ['月', '火', '水', '木', '金', '土', '日']

SLOT_MINUTES = 15
SLOT_HEIGHT = 28  # px per 15-minute slot on the timeline
HOUR_HEIGHT = SLOT_HEIGHT * (60 // SLOT_MINUTES)
DAY_HEIGHT = HOUR_HEIGHT * 24
DEFAULT_START_TIME = time(9, 0)
HOUR_OPTIONS = [f'{h:02d}' for h in range(24)]
MINUTE_OPTIONS = ['00', '15', '30', '45']


def _snap_time(raw):
    """Parse an 'HH:MM' string and round it to the nearest 15-minute slot."""
    if not raw:
        return None
    parsed = datetime.strptime(raw, '%H:%M').time()
    total = parsed.hour * 60 + parsed.minute
    snapped = min(round(total / SLOT_MINUTES) * SLOT_MINUTES, 23 * 60 + 45)
    return time(snapped // 60, snapped % 60)


def _snap_duration(raw):
    """Round a minute count to the nearest 15-minute slot, minimum one slot."""
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        return 60
    if minutes <= 0:
        return SLOT_MINUTES
    return max(SLOT_MINUTES, round(minutes / SLOT_MINUTES) * SLOT_MINUTES)


def _item_position(item):
    """Return (top_px, height_px) on the timeline for an item's start_time/duration."""
    start = item.start_time or DEFAULT_START_TIME
    total_min = start.hour * 60 + start.minute
    top = (total_min // SLOT_MINUTES) * SLOT_HEIGHT
    dur_slots = max(1, item.duration_minutes // SLOT_MINUTES)
    return top, dur_slots * SLOT_HEIGHT


def _end_time_str(item):
    """Return the item's end time as 'HH:MM', wrapping past midnight."""
    start = item.start_time or DEFAULT_START_TIME
    total = (start.hour * 60 + start.minute + item.duration_minutes) % (24 * 60)
    return f'{total // 60:02d}:{total % 60:02d}'


def _calendar_url(plan, item):
    """Build a Google Calendar 'add event' link for a wake-up alarm, or None if the plan has no start date."""
    if not plan.start_date:
        return None
    event_date = plan.start_date + timedelta(days=item.day_number - 1)
    start = item.start_time or DEFAULT_START_TIME
    start_dt = datetime.combine(event_date, start)
    end_dt = start_dt + timedelta(minutes=item.duration_minutes)
    fmt = '%Y%m%dT%H%M%S'
    params = {
        'action': 'TEMPLATE',
        'text': f'{item.name}(アラーム)',
        'dates': f'{start_dt.strftime(fmt)}/{end_dt.strftime(fmt)}',
        'details': f'{plan.name} の起床アラームです',
    }
    return 'https://calendar.google.com/calendar/render?' + urlencode(params)


def _assign_overlap_columns(items):
    """Lay out same-day items so overlapping ones sit side by side instead of stacking.

    Items are grouped into clusters of mutually-overlapping time ranges. Within
    each cluster, the longest-duration item claims column 0 (leftmost) and the
    rest are greedily packed into the first column that doesn't conflict.
    Sets item.left_pct / item.width_pct (percent of the timeline's width).
    """
    entries = []
    for item in items:
        start = item.start_time or DEFAULT_START_TIME
        start_min = start.hour * 60 + start.minute
        entries.append({
            'item': item,
            'start': start_min,
            'end': start_min + item.duration_minutes,
        })

    by_start = sorted(entries, key=lambda e: e['start'])
    clusters = []
    cluster, cluster_end = [], None
    for e in by_start:
        if cluster and e['start'] < cluster_end:
            cluster.append(e)
            cluster_end = max(cluster_end, e['end'])
        else:
            if cluster:
                clusters.append(cluster)
            cluster, cluster_end = [e], e['end']
    if cluster:
        clusters.append(cluster)

    for cluster in clusters:
        ordered = sorted(cluster, key=lambda e: (-(e['end'] - e['start']), e['start'], e['item'].pk))
        columns = []  # list of lists of entries already placed in that column
        for e in ordered:
            for col_idx, col_entries in enumerate(columns):
                if all(e['start'] >= o['end'] or e['end'] <= o['start'] for o in col_entries):
                    col_entries.append(e)
                    e['col'] = col_idx
                    break
            else:
                columns.append([e])
                e['col'] = len(columns) - 1
        total = len(columns)
        for e in cluster:
            e['total'] = total

    for e in entries:
        total = e.get('total', 1)
        col = e.get('col', 0)
        e['item'].left_pct = round(col * 100 / total, 4)
        e['item'].width_pct = round(100 / total, 4)


def _get_editable_plan_or_404(pk, user):
    """Fetch a plan only if the user may edit its schedule (owner only)."""
    plan = get_object_or_404(TravelPlan, pk=pk)
    if not plan.can_edit(user):
        raise Http404
    return plan


def _get_viewable_plan_or_404(pk, user):
    """Fetch a plan the user may open and respond to: the owner, or a member of
    the group it's shared with. They cannot edit the schedule itself."""
    plan = get_object_or_404(TravelPlan, pk=pk)
    if not plan.can_view(user):
        raise Http404
    return plan


RETIRED_DEFAULT_CARDS = [
    '電車・バス移動',
    '車', '電車', 'バス', '飛行機', '徒歩', '自転車',
    '朝食', '昼食', '夕食', '夜ご飯',
    '観光スポット',
    'ホテルチェックイン', 'ホテルチェックアウト',
    '予備',
    '起床',
]


def ensure_defaults(user):
    existing_names = set(
        CardTemplate.objects.filter(user=user, is_default=True).values_list('name', flat=True)
    )
    for name, ctype in DEFAULT_CARDS:
        if name not in existing_names:
            CardTemplate.objects.create(user=user, name=name, card_type=ctype, is_default=True)
    CardTemplate.objects.filter(user=user, is_default=True, name__in=RETIRED_DEFAULT_CARDS).delete()


DEMO_USERNAME = '__demo_showcase__'
DEMO_PLAN_NAME = '京都1日観光'
DEMO_ITEMS = [
    ('起床', 'wake', time(6, 30), 15, ''),
    ('朝食', 'eat', time(7, 0), 45, 'ホテルのビュッフェ'),
    ('電車', 'move', time(8, 0), 45, ''),
    ('清水寺', 'see', time(9, 0), 120, ''),
    ('昼食', 'eat', time(12, 0), 60, '祇園でランチ'),
    ('嵐山散策', 'see', time(13, 30), 120, ''),
    ('ホテルチェックイン', 'stay', time(16, 30), 30, ''),
    ('夕食', 'eat', time(18, 30), 90, '懐石料理'),
]


def _get_demo_plan_items():
    """Get (creating if needed) the read-only showcase plan featured on the login page."""
    user, user_created = User.objects.get_or_create(username=DEMO_USERNAME)
    if user_created:
        user.set_unusable_password()
        user.save()
    plan, plan_created = TravelPlan.objects.get_or_create(user=user, name=DEMO_PLAN_NAME)
    if plan_created or not plan.schedule_items.exists():
        plan.schedule_items.all().delete()
        for name, ctype, start, duration, memo in DEMO_ITEMS:
            ScheduleItem.objects.create(
                plan=plan, name=name, card_type=ctype, day_number=1,
                start_time=start, duration_minutes=duration, memo=memo,
            )
    items = list(plan.schedule_items.filter(day_number=1))
    for item in items:
        item.start_time_str = (item.start_time or DEFAULT_START_TIME).strftime('%H:%M')
        item.end_time_str = _end_time_str(item)
    return items


def login_view(request):
    if request.user.is_authenticated:
        return redirect('top')
    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '')
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            ensure_defaults(user)
            profile, _ = Profile.objects.get_or_create(user=user)
            if not profile.home_address:
                return redirect('set_home_address')
            return redirect('top')
        error = 'ユーザー名またはパスワードが正しくありません'
    return render(request, 'travel/login.html', {
        'error': error,
        'demo_items': _get_demo_plan_items(),
        'demo_plan_name': DEMO_PLAN_NAME,
    })


def register_view(request):
    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        home_address = request.POST.get('home_address', '').strip()
        if User.objects.filter(username=username).exists():
            error = 'そのユーザー名はすでに使われています'
        elif len(password) < 4:
            error = 'パスワードは4文字以上にしてください'
        else:
            user = User.objects.create_user(username=username, password=password)
            login(request, user)
            ensure_defaults(user)
            Profile.objects.create(user=user, home_address=home_address)
            if not home_address:
                return redirect('set_home_address')
            return redirect('top')
    return render(request, 'travel/register.html', {'error': error})


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def set_home_address_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        profile.home_address = request.POST.get('home_address', '').strip()
        profile.save(update_fields=['home_address'])
        return redirect('top')
    return render(request, 'travel/set_address.html', {'profile': profile})


@login_required
def my_info_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    plans = TravelPlan.objects.filter(user=request.user)
    return render(request, 'travel/my_info.html', {'profile': profile, 'plans': plans})


@login_required
def top_view(request):
    plans = list(TravelPlan.objects.filter(
        Q(user=request.user) | Q(group__owner=request.user) | Q(group__members=request.user)
    ).distinct())
    for plan in plans:
        plan.my_like = plan.is_liked_by(request.user)
        plan.like_count = plan.likes.count()
    return render(request, 'travel/top.html', {'plans': plans})


@login_required
def plan_new(request):
    if request.method == 'POST':
        name = request.POST.get('name', '無題のプラン')
        start = request.POST.get('start_date') or None
        end = request.POST.get('end_date') or None
        try:
            participant_count = max(1, int(request.POST.get('participant_count', 1)))
        except (TypeError, ValueError):
            participant_count = 1
        plan = TravelPlan.objects.create(
            user=request.user, name=name, start_date=start, end_date=end,
            participant_count=participant_count,
        )
        return redirect('plan_edit', pk=plan.pk)
    return render(request, 'travel/plan_new.html')


def _build_days_data(plan, user=None):
    days = range(1, plan.day_count + 1)
    days_data = []
    member_count = len(plan.group.all_member_ids()) if plan.group_id else 0
    is_owner = bool(user and plan.user_id == user.id)
    for d in days:
        items = list(plan.schedule_items.filter(day_number=d))
        responses_by_item = {}
        if items:
            item_ids = [i.pk for i in items]
            for r in CardResponse.objects.filter(item_id__in=item_ids).select_related('user'):
                responses_by_item.setdefault(r.item_id, []).append(r)
        for item in items:
            item.top_px, item.height_px = _item_position(item)
            item.start_time_str = (item.start_time or DEFAULT_START_TIME).strftime('%H:%M')
            item.end_time_str = _end_time_str(item)
            if item.card_type == 'wake':
                item.calendar_url = _calendar_url(plan, item)
            if item.approval_enabled:
                item_responses = responses_by_item.get(item.pk, [])
                item.approved_count = sum(1 for r in item_responses if r.status == 'approved')
                item.rejected_count = sum(1 for r in item_responses if r.status == 'rejected')
                item.member_count = member_count
                item.my_response = next(
                    (r.status for r in item_responses if user and r.user_id == user.id), None
                )
                if is_owner:
                    item.reject_comments = [
                        r for r in item_responses if r.status == 'rejected' and r.comment
                    ]
        _assign_overlap_columns(items)
        date = plan.start_date + timedelta(days=d - 1) if plan.start_date else None
        date_str = f'{date.month}月{date.day}日({WEEKDAY_JA[date.weekday()]})' if date else None
        days_data.append({'number': d, 'items': items, 'date_str': date_str})
    return days, days_data


@login_required
def plan_edit(request, pk):
    plan = _get_viewable_plan_or_404(pk, request.user)
    is_owner = plan.user_id == request.user.id
    if request.method == 'POST':
        if is_owner:
            new_name = request.POST.get('name')
            if new_name:
                plan.name = new_name
                plan.save(update_fields=["name"])
        return redirect('top')
    ensure_defaults(request.user)
    templates = _ordered_templates(request.user)
    days, days_data = _build_days_data(plan, user=request.user)
    share_url = request.build_absolute_uri(reverse('plan_share', args=[plan.share_token]))
    my_groups = Group.objects.filter(owner=request.user) if is_owner else Group.objects.none()
    chat_messages = plan.group.messages.select_related('user') if plan.group_id else None
    plan.my_like = plan.is_liked_by(request.user)
    plan.like_count = plan.likes.count()
    return render(request, 'travel/plan_edit.html', {
        'plan': plan,
        'templates': templates,
        'days': days,
        'days_data': days_data,
        'hour_marks': [{'label': f'{h:02d}:00', 'top': h * HOUR_HEIGHT} for h in range(24)],
        'slot_height': SLOT_HEIGHT,
        'hour_height': HOUR_HEIGHT,
        'day_height': DAY_HEIGHT,
        'hour_options': HOUR_OPTIONS,
        'minute_options': MINUTE_OPTIONS,
        'share_url': share_url,
        'is_owner': is_owner,
        'my_groups': my_groups,
        'chat_messages': chat_messages,
        'subtype_choices_json': json.dumps(SUBTYPE_CHOICES, ensure_ascii=False),
        'home_address_json': json.dumps(getattr(getattr(request.user, 'profile', None), 'home_address', '') or ''),
    })


HOME_LABELS = ('自宅', '家')


@login_required
def plan_map(request, pk):
    plan = _get_viewable_plan_or_404(pk, request.user)
    owner_profile = getattr(plan.user, 'profile', None)
    home_address = owner_profile.home_address if owner_profile else ''

    def geocode_query(label):
        # "自宅"/"家" are never real place names Nominatim can resolve; swap in
        # the plan owner's registered address for the lookup, but keep showing
        # the "自宅" label on the map (not the raw address) for privacy.
        if label in HOME_LABELS and home_address:
            return home_address
        return label

    seen = set()
    locations = []
    segments = []
    for item in plan.schedule_items.order_by('day_number', 'order'):
        candidates = []
        if item.card_type == 'move':
            if item.from_location:
                candidates.append(item.from_location.strip())
            if item.to_location:
                candidates.append(item.to_location.strip())
            if item.from_location and item.to_location:
                segments.append({
                    'from': item.from_location.strip(),
                    'to': item.to_location.strip(),
                    'mode': item.name,
                })
        elif item.card_type in ('see', 'stay'):
            candidates.append(item.name.strip())
        for label in candidates:
            if label and label not in seen:
                seen.add(label)
                locations.append({'label': label, 'day': item.day_number, 'query': geocode_query(label)})
    return render(request, 'travel/plan_map.html', {
        'plan': plan, 'locations': locations, 'segments': segments,
    })


def plan_share(request, token):
    plan = get_object_or_404(TravelPlan, share_token=token)
    days, days_data = _build_days_data(plan)
    return render(request, 'travel/plan_share.html', {
        'plan': plan,
        'days': days,
        'days_data': days_data,
        'hour_marks': [{'label': f'{h:02d}:00', 'top': h * HOUR_HEIGHT} for h in range(24)],
        'slot_height': SLOT_HEIGHT,
        'hour_height': HOUR_HEIGHT,
        'day_height': DAY_HEIGHT,
    })


@login_required
def plan_delete(request, pk):
    plan = get_object_or_404(TravelPlan, pk=pk, user=request.user)
    if request.method == 'POST':
        plan.delete()
    return redirect('top')


@login_required
@require_POST
def plan_like_toggle(request, pk):
    plan = _get_viewable_plan_or_404(pk, request.user)
    like = PlanLike.objects.filter(plan=plan, user=request.user).first()
    if like:
        like.delete()
    else:
        PlanLike.objects.create(plan=plan, user=request.user)
    return redirect(request.META.get('HTTP_REFERER') or 'top')


@login_required
@require_POST
def plan_set_group(request, pk):
    plan = get_object_or_404(TravelPlan, pk=pk, user=request.user)
    group_id = request.POST.get('group_id')
    if group_id:
        plan.group = get_object_or_404(Group, pk=group_id, owner=request.user)
    else:
        plan.group = None
    plan.save(update_fields=['group'])
    return redirect('plan_edit', pk=plan.pk)


@login_required
@require_POST
def plan_set_participants(request, pk):
    plan = get_object_or_404(TravelPlan, pk=pk, user=request.user)
    try:
        plan.participant_count = max(1, int(request.POST.get('participant_count', 1)))
    except (TypeError, ValueError):
        pass
    else:
        plan.save(update_fields=['participant_count'])
    return redirect('plan_edit', pk=plan.pk)


@login_required
@require_POST
def plan_toggle_warikan(request, pk):
    plan = get_object_or_404(TravelPlan, pk=pk, user=request.user)
    plan.warikan_enabled = not plan.warikan_enabled
    plan.save(update_fields=['warikan_enabled'])
    return redirect('plan_edit', pk=plan.pk)


@login_required
def group_list(request):
    owned_groups = Group.objects.filter(owner=request.user)
    joined_groups = Group.objects.filter(members=request.user).exclude(owner=request.user)
    return render(request, 'travel/group_list.html', {
        'owned_groups': owned_groups,
        'joined_groups': joined_groups,
    })


@login_required
def group_new(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if name:
            group = Group.objects.create(name=name, owner=request.user)
            return redirect('group_detail', pk=group.pk)
    return render(request, 'travel/group_new.html')


@login_required
def group_detail(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if not group.is_member(request.user):
        raise Http404
    is_owner = group.owner_id == request.user.id
    error = None
    if request.method == 'POST':
        if not is_owner:
            raise Http404
        username = request.POST.get('username', '').strip()
        new_member = User.objects.filter(username=username).first()
        if not new_member:
            error = 'そのユーザー名は見つかりません'
        elif new_member.id == group.owner_id:
            error = 'グループのオーナーはすでにメンバーです'
        else:
            group.members.add(new_member)
    return render(request, 'travel/group_detail.html', {
        'group': group,
        'is_owner': is_owner,
        'error': error,
        'shared_plans': group.plans.all(),
        'chat_messages': group.messages.select_related('user'),
    })


@login_required
@require_POST
def group_send_message(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if not group.is_member(request.user):
        raise Http404
    text = request.POST.get('text', '').strip()
    if text:
        GroupMessage.objects.create(group=group, user=request.user, text=text)
    return redirect('group_detail', pk=group.pk)


@login_required
def api_group_messages(request, group_pk):
    group = get_object_or_404(Group, pk=group_pk)
    if not group.is_member(request.user):
        raise Http404
    if request.method == 'POST':
        data = json.loads(request.body)
        text = data.get('text', '').strip()
        if text:
            GroupMessage.objects.create(group=group, user=request.user, text=text)
    messages = group.messages.select_related('user')
    return JsonResponse({
        'messages': [
            {
                'id': m.pk,
                'username': m.user.username,
                'text': m.text,
                'created_at': m.created_at.strftime('%m/%d %H:%M'),
                'is_mine': m.user_id == request.user.id,
            }
            for m in messages
        ]
    })


@login_required
@require_POST
def group_remove_member(request, pk, user_id):
    group = get_object_or_404(Group, pk=pk, owner=request.user)
    group.members.remove(user_id)
    return redirect('group_detail', pk=group.pk)


@login_required
@require_POST
def group_leave(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if group.owner_id == request.user.id:
        raise Http404
    group.members.remove(request.user)
    return redirect('group_list')


@login_required
@require_POST
def group_delete(request, pk):
    group = get_object_or_404(Group, pk=pk, owner=request.user)
    group.delete()
    return redirect('group_list')


@login_required
def notifications_view(request):
    rejections = (
        CardResponse.objects.filter(status='rejected', item__plan__user=request.user)
        .exclude(comment='')
        .select_related('item', 'item__plan', 'user')
    )
    likes = (
        PlanLike.objects.filter(plan__user=request.user)
        .exclude(user=request.user)
        .select_related('plan', 'user')
    )
    entries = []
    for r in rejections:
        entries.append({
            'kind': 'reject', 'pk': r.pk, 'is_read': r.is_read, 'timestamp': r.updated_at,
            'user': r.user, 'plan': r.item.plan, 'item': r.item, 'comment': r.comment,
        })
    for like in likes:
        entries.append({
            'kind': 'like', 'pk': like.pk, 'is_read': like.is_read, 'timestamp': like.created_at,
            'user': like.user, 'plan': like.plan,
        })
    entries.sort(key=lambda e: e['timestamp'], reverse=True)
    return render(request, 'travel/notifications.html', {'notifications': entries})


@login_required
@require_POST
def notification_read(request, pk):
    resp = get_object_or_404(CardResponse, pk=pk, status='rejected', item__plan__user=request.user)
    if not resp.is_read:
        resp.is_read = True
        resp.save(update_fields=['is_read'])
    return redirect('plan_edit', pk=resp.item.plan_id)


@login_required
@require_POST
def plan_like_read(request, pk):
    like = get_object_or_404(PlanLike, pk=pk, plan__user=request.user)
    if not like.is_read:
        like.is_read = True
        like.save(update_fields=['is_read'])
    return redirect('plan_edit', pk=like.plan_id)


@login_required
def card_templates(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        ctype = request.POST.get('card_type', 'free')
        if name:
            CardTemplate.objects.create(user=request.user, name=name, card_type=ctype)
        return redirect('card_templates')
    ensure_defaults(request.user)
    templates = _ordered_templates(request.user)
    return render(request, 'travel/card_templates.html', {'templates': templates})


@login_required
def card_template_delete(request, pk):
    t = get_object_or_404(CardTemplate, pk=pk, user=request.user)
    if request.method == 'POST':
        t.delete()
    return redirect('card_templates')


@login_required
@require_POST
def api_add_item(request, plan_pk):
    plan = _get_editable_plan_or_404(plan_pk, request.user)
    data = json.loads(request.body)
    day = int(data.get('day', 1))
    tpl_id = data.get('template_id')
    tpl = get_object_or_404(CardTemplate, pk=tpl_id, user=request.user)
    order = plan.schedule_items.filter(day_number=day).count()
    start_time = _snap_time(data.get('start_time')) or DEFAULT_START_TIME
    duration_minutes = _snap_duration(data.get('duration_minutes'))
    memo = data.get('memo', '')
    alarm_enabled = bool(data.get('alarm_enabled')) and tpl.card_type == 'wake'
    from_location = data.get('from_location', '').strip() if tpl.card_type == 'move' else ''
    to_location = data.get('to_location', '').strip() if tpl.card_type == 'move' else ''
    subtype = data.get('subtype', '').strip()
    name = subtype if subtype in SUBTYPE_CHOICES.get(tpl.card_type, []) else tpl.name
    item = ScheduleItem.objects.create(
        plan=plan, template=tpl, name=name, card_type=tpl.card_type,
        day_number=day, order=order, start_time=start_time,
        duration_minutes=duration_minutes, memo=memo, alarm_enabled=alarm_enabled,
        from_location=from_location, to_location=to_location,
    )
    return JsonResponse({
        'id': item.pk, 'name': item.name, 'card_type': item.card_type, 'day': day,
        'start_time': item.start_time.strftime('%H:%M') if item.start_time else None,
        'duration_minutes': item.duration_minutes,
        'memo': item.memo,
        'alarm_enabled': item.alarm_enabled,
        'from_location': item.from_location,
        'to_location': item.to_location,
    })


@login_required
@require_POST
def api_update_time(request, plan_pk, item_pk):
    plan = _get_editable_plan_or_404(plan_pk, request.user)
    item = get_object_or_404(ScheduleItem, pk=item_pk, plan=plan)
    data = json.loads(request.body)
    if data.get('start_time'):
        item.start_time = _snap_time(data['start_time'])
    if data.get('duration_minutes'):
        item.duration_minutes = int(data['duration_minutes'])
    if 'memo' in data:
        item.memo = data['memo']
    if 'from_location' in data and item.card_type == 'move':
        item.from_location = data['from_location'].strip()
    if 'to_location' in data and item.card_type == 'move':
        item.to_location = data['to_location'].strip()
    if 'alarm_enabled' in data:
        item.alarm_enabled = bool(data['alarm_enabled']) and item.card_type == 'wake'
    if 'approval_enabled' in data and plan.user_id == request.user.id:
        item.approval_enabled = bool(data['approval_enabled'])
    if 'cost' in data:
        try:
            item.cost = max(0, int(data['cost'] or 0))
        except (TypeError, ValueError):
            pass
    if 'day' in data and int(data['day']) != item.day_number:
        item.day_number = int(data['day'])
        item.order = plan.schedule_items.filter(day_number=item.day_number).count()
    item.save(update_fields=[
        'start_time', 'duration_minutes', 'memo', 'from_location', 'to_location',
        'alarm_enabled', 'approval_enabled', 'cost', 'day_number', 'order',
    ])
    return JsonResponse({
        'id': item.pk,
        'start_time': item.start_time.strftime('%H:%M') if item.start_time else None,
        'duration_minutes': item.duration_minutes,
        'alarm_enabled': item.alarm_enabled,
        'approval_enabled': item.approval_enabled,
        'memo': item.memo,
        'from_location': item.from_location,
        'to_location': item.to_location,
        'cost': item.cost,
        'cost_per_person': item.cost_per_person,
        'day': item.day_number,
    })


@login_required
@require_POST
def api_remove_item(request, plan_pk, item_pk):
    plan = _get_editable_plan_or_404(plan_pk, request.user)
    item = get_object_or_404(ScheduleItem, pk=item_pk, plan=plan)
    item.delete()
    return JsonResponse({'ok': True})


@login_required
@require_POST
def api_reorder(request, plan_pk):
    plan = _get_editable_plan_or_404(plan_pk, request.user)
    data = json.loads(request.body)
    for entry in data:
        ScheduleItem.objects.filter(pk=entry['id'], plan=plan).update(
            day_number=entry['day'], order=entry['order']
        )
    return JsonResponse({'ok': True})


@login_required
@require_POST
def api_set_response(request, plan_pk, item_pk):
    plan = _get_viewable_plan_or_404(plan_pk, request.user)
    item = get_object_or_404(ScheduleItem, pk=item_pk, plan=plan, approval_enabled=True)
    existing = CardResponse.objects.filter(item=item, user=request.user).first()
    if existing:
        # Once a person has responded, their choice is locked in and can't be changed.
        return JsonResponse({'error': 'すでに回答済みです', 'my_response': existing.status}, status=400)
    data = json.loads(request.body)
    status = data.get('status')
    if status in ('approved', 'rejected'):
        comment = data.get('comment', '').strip() if status == 'rejected' else ''
        CardResponse.objects.create(item=item, user=request.user, status=status, comment=comment)
    result = {
        'id': item.pk,
        'my_response': status if status in ('approved', 'rejected') else None,
    }
    if plan.user_id == request.user.id:
        responses = list(item.responses.all())
        result['approved_count'] = sum(1 for r in responses if r.status == 'approved')
        result['rejected_count'] = sum(1 for r in responses if r.status == 'rejected')
        result['member_count'] = len(plan.group.all_member_ids()) if plan.group_id else 0
    return JsonResponse(result)
