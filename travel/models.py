import uuid
from django.db import models
from django.contrib.auth.models import User


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


class TravelPlan(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='plans')
    name = models.CharField(max_length=200)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    share_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    is_liked = models.BooleanField(default=False)
    group = models.ForeignKey(Group, on_delete=models.SET_NULL, null=True, blank=True, related_name='plans')
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

    def can_edit(self, user):
        if self.user_id == user.id:
            return True
        return bool(self.group_id and self.group.is_member(user))


class CardTemplate(models.Model):
    TYPE_CHOICES = [
        ('wake', '起床'),
        ('move', '移動'),
        ('eat', '食事'),
        ('see', '観光'),
        ('stay', '宿泊'),
        ('free', 'フリー'),
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
    alarm_enabled = models.BooleanField(default=False)
    approval_enabled = models.BooleanField(default=False)

    class Meta:
        ordering = ['day_number', 'order']

    def __str__(self):
        return f"{self.plan.name} - Day{self.day_number}: {self.name}"


class CardResponse(models.Model):
    STATUS_CHOICES = [
        ('approved', '承諾'),
        ('rejected', '拒否'),
    ]
    item = models.ForeignKey(ScheduleItem, on_delete=models.CASCADE, related_name='responses')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    comment = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('item', 'user')

    def __str__(self):
        return f"{self.user.username}: {self.get_status_display()} ({self.item.name})"