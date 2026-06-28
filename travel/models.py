from django.db import models
from django.contrib.auth.models import User


class TravelPlan(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='plans')
    name = models.CharField(max_length=200)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
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


class CardTemplate(models.Model):
    TYPE_CHOICES = [
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
    memo = models.TextField(blank=True)

    class Meta:
        ordering = ['day_number', 'order']

    def __str__(self):
        return f"{self.plan.name} - Day{self.day_number}: {self.name}"
