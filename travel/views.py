import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from .models import TravelPlan, CardTemplate, ScheduleItem

DEFAULT_CARDS = [
    ('電車・バス移動', 'move'),
    ('飛行機', 'move'),
    ('朝食', 'eat'),
    ('昼食', 'eat'),
    ('夕食', 'eat'),
    ('観光スポット', 'see'),
    ('ホテルチェックイン', 'stay'),
    ('ホテルチェックアウト', 'stay'),
]


def ensure_defaults(user):
    if not CardTemplate.objects.filter(user=user, is_default=True).exists():
        for name, ctype in DEFAULT_CARDS:
            CardTemplate.objects.create(user=user, name=name, card_type=ctype, is_default=True)


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
            return redirect('top')
        error = 'ユーザー名またはパスワードが正しくありません'
    return render(request, 'travel/login.html', {'error': error})


def register_view(request):
    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '')
        password = request.POST.get('password', '')
        if User.objects.filter(username=username).exists():
            error = 'そのユーザー名はすでに使われています'
        elif len(password) < 4:
            error = 'パスワードは4文字以上にしてください'
        else:
            user = User.objects.create_user(username=username, password=password)
            login(request, user)
            ensure_defaults(user)
            return redirect('top')
    return render(request, 'travel/register.html', {'error': error})


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def top_view(request):
    plans = TravelPlan.objects.filter(user=request.user)
    return render(request, 'travel/top.html', {'plans': plans})


@login_required
def plan_new(request):
    if request.method == 'POST':
        name = request.POST.get('name', '無題のプラン')
        start = request.POST.get('start_date') or None
        end = request.POST.get('end_date') or None
        plan = TravelPlan.objects.create(user=request.user, name=name, start_date=start, end_date=end)
        return redirect('plan_edit', pk=plan.pk)
    return render(request, 'travel/plan_new.html')


@login_required
def plan_edit(request, pk):
    plan = get_object_or_404(TravelPlan, pk=pk, user=request.user)
    if request.method == 'POST':
        plan.name = request.POST.get('name', plan.name)
        plan.save(update_fields=["name"])
        return redirect('top')
    templates = CardTemplate.objects.filter(user=request.user)
    days = range(1, plan.day_count + 1)
    days_data = []
    for d in days:
        days_data.append({'number':d,'items':list(plan.schedule_items.filter(day_number=d))})
    return render(request, 'travel/plan_edit.html', {
        'plan': plan,
        'templates': templates,
        'days': days,
        'days_data': days_data,
    })


@login_required
def plan_delete(request, pk):
    plan = get_object_or_404(TravelPlan, pk=pk, user=request.user)
    if request.method == 'POST':
        plan.delete()
    return redirect('top')


@login_required
def card_templates(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        ctype = request.POST.get('card_type', 'free')
        if name:
            CardTemplate.objects.create(user=request.user, name=name, card_type=ctype)
        return redirect('card_templates')
    templates = CardTemplate.objects.filter(user=request.user)
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
    plan = get_object_or_404(TravelPlan, pk=plan_pk, user=request.user)
    data = json.loads(request.body)
    day = int(data.get('day', 1))
    tpl_id = data.get('template_id')
    tpl = get_object_or_404(CardTemplate, pk=tpl_id, user=request.user)
    order = plan.schedule_items.filter(day_number=day).count()
    item = ScheduleItem.objects.create(
        plan=plan, template=tpl, name=tpl.name, card_type=tpl.card_type,
        day_number=day, order=order
    )
    return JsonResponse({'id': item.pk, 'name': item.name, 'card_type': item.card_type, 'day': day})


@login_required
@require_POST
def api_remove_item(request, plan_pk, item_pk):
    plan = get_object_or_404(TravelPlan, pk=plan_pk, user=request.user)
    item = get_object_or_404(ScheduleItem, pk=item_pk, plan=plan)
    item.delete()
    return JsonResponse({'ok': True})


@login_required
@require_POST
def api_reorder(request, plan_pk):
    plan = get_object_or_404(TravelPlan, pk=plan_pk, user=request.user)
    data = json.loads(request.body)
    for entry in data:
        ScheduleItem.objects.filter(pk=entry['id'], plan=plan).update(
            day_number=entry['day'], order=entry['order']
        )
    return JsonResponse({'ok': True})
