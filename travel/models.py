import secrets
import string
import uuid
from django.db import models
from django.contrib.auth.models import User

USER_CODE_ALPHABET = string.ascii_letters + string.digits


def generate_user_code():
    """xxxx-xxxx of random letters/digits — an alphanumeric+symbol ID people
    can search for and share without exposing their username/email."""
    part1 = ''.join(secrets.choice(USER_CODE_ALPHABET) for _ in range(4))
    part2 = ''.join(secrets.choice(USER_CODE_ALPHABET) for _ in range(4))
    return f'{part1}-{part2}'


def generate_unique_user_code():
    while True:
        code = generate_user_code()
        if not Profile.objects.filter(user_code=code).exists():
            return code


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    # Deliberately coarse: town-level only (e.g. "東京都渋谷区渋谷"), never a full
    # street address, since this gets baked into move cards other people can see.
    home_address = models.CharField(max_length=200, blank=True, default='')
    # Auto-generated at registration (see generate_user_code), user-editable
    # afterwards. Search key for adding group members instead of username,
    # since usernames here are often full email addresses.
    user_code = models.CharField(max_length=32, unique=True, null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} の住所"

    def ensure_user_code(self):
        if not self.user_code:
            self.user_code = generate_unique_user_code()
            self.save(update_fields=['user_code'])
        return self.user_code


class Group(models.Model):
    name = models.CharField(max_length=100)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_groups')
    members = models.ManyToManyField(User, related_name='travel_groups', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def is_member(self, user):
        return self.owner_id == user.id or self.members.filter(pk=user.id).exists()

    def all_member_ids(self):
        return {self.owner_id, *self.members.values_list('pk', flat=True)}


class GroupMessage(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='messages')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    text = models.TextField()
    mentions = models.ManyToManyField(User, related_name='chat_mentions', blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.user.username}: {self.text[:30]}"


class TravelPlan(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='plans')
    name = models.CharField(max_length=200)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    share_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    group = models.ForeignKey(Group, on_delete=models.SET_NULL, null=True, blank=True, related_name='plans')
    participant_count = models.PositiveIntegerField(default=1)
    warikan_enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @property
    def day_count(self):
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return 1

    @property
    def total_cards(self):
        return self.schedule_items.count()

    @property
    def total_cost(self):
        return sum(item.cost for item in self.schedule_items.all())

    @property
    def total_cost_per_person(self):
        return round(self.total_cost / (self.participant_count or 1))

    def can_edit(self, user):
        """The owner may always edit. A group member may also edit schedule
        cards (not plan-level settings) once the owner has approved their
        edit request; see EditRequest."""
        if self.user_id == user.id:
            return True
        return self.edit_requests.filter(user=user, status='approved').exists()

    def can_view(self, user):
        """Owner or a member of the plan's group may open the plan and respond to cards."""
        if self.user_id == user.id:
            return True
        return bool(self.group_id and self.group.is_member(user))

    def is_liked_by(self, user):
        return self.likes.filter(user=user).exists()


class CardTemplate(models.Model):
    TYPE_CHOICES = [
        ('wake', '起床'),
        ('move', '移動'),
        ('eat', 'ご飯'),
        ('see', '観光'),
        ('stay', 'ホテル'),
        ('other', 'その他'),
        ('free', '予備'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='card_templates')
    name = models.CharField(max_length=200)
    card_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='free')
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['is_default', 'card_type', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_card_type_display()})"


class ScheduleItem(models.Model):
    plan = models.ForeignKey(TravelPlan, on_delete=models.CASCADE, related_name='schedule_items')
    template = models.ForeignKey(CardTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=200)
    card_type = models.CharField(max_length=10, choices=CardTemplate.TYPE_CHOICES, default='free')
    day_number = models.PositiveIntegerField(default=1)
    order = models.PositiveIntegerField(default=0)
    start_time = models.TimeField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(default=60)
    memo = models.TextField(blank=True)
    from_location = models.CharField(max_length=200, blank=True)
    to_location = models.CharField(max_length=200, blank=True)
    alarm_enabled = models.BooleanField(default=False)
    approval_enabled = models.BooleanField(default=False)
    cost = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['day_number', 'order']

    def __str__(self):
        return f"{self.plan.name} - Day{self.day_number}: {self.name}"

    @property
    def cost_per_person(self):
        if not self.cost:
            return 0
        return round(self.cost / (self.plan.participant_count or 1))


class CardResponse(models.Model):
    STATUS_CHOICES = [
        ('approved', '承諾'),
        ('rejected', '拒否'),
    ]
    item = models.ForeignKey(ScheduleItem, on_delete=models.CASCADE, related_name='responses')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    comment = models.TextField(blank=True)
    is_read = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('item', 'user')

    def __str__(self):
        return f"{self.user.username}: {self.get_status_display()} ({self.item.name})"


class PlanLike(models.Model):
    plan = models.ForeignKey(TravelPlan, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('plan', 'user')

    def __str__(self):
        return f"{self.user.username} likes {self.plan.name}"


class EditRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', '申請中'),
        ('approved', '許可'),
        ('rejected', '却下'),
    ]
    plan = models.ForeignKey(TravelPlan, on_delete=models.CASCADE, related_name='edit_requests')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    # Whether the requester has seen the owner's decision (approved/rejected).
    # Meaningless while status is still 'pending' — that's surfaced to the
    # owner via the plain existence of a pending row, not a read flag.
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('plan', 'user')

    def __str__(self):
        return f"{self.user.username} -> {self.plan.name}: {self.get_status_display()}"