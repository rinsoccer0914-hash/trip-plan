from django.urls import path
from . import views

urlpatterns = [
    path('', views.top_view, name='top'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('plan/new/', views.plan_new, name='plan_new'),
    path('plan/<int:pk>/edit/', views.plan_edit, name='plan_edit'),
    path('plan/<int:pk>/delete/', views.plan_delete, name='plan_delete'),
    path('plan/<int:pk>/like/', views.plan_like_toggle, name='plan_like_toggle'),
    path('plan/<int:pk>/set-group/', views.plan_set_group, name='plan_set_group'),
    path('share/<uuid:token>/', views.plan_share, name='plan_share'),
    path('cards/', views.card_templates, name='card_templates'),
    path('cards/<int:pk>/delete/', views.card_template_delete, name='card_template_delete'),
    path('groups/', views.group_list, name='group_list'),
    path('groups/new/', views.group_new, name='group_new'),
    path('groups/<int:pk>/', views.group_detail, name='group_detail'),
    path('groups/<int:pk>/remove-member/<int:user_id>/', views.group_remove_member, name='group_remove_member'),
    path('groups/<int:pk>/leave/', views.group_leave, name='group_leave'),
    path('groups/<int:pk>/delete/', views.group_delete, name='group_delete'),
    path('notifications/', views.notifications_view, name='notifications'),
    path('api/plan/<int:plan_pk>/add/', views.api_add_item, name='api_add_item'),
    path('api/plan/<int:plan_pk>/remove/<int:item_pk>/', views.api_remove_item, name='api_remove_item'),
    path('api/plan/<int:plan_pk>/item/<int:item_pk>/time/', views.api_update_time, name='api_update_time'),
    path('api/plan/<int:plan_pk>/item/<int:item_pk>/response/', views.api_set_response, name='api_set_response'),
    path('api/plan/<int:plan_pk>/reorder/', views.api_reorder, name='api_reorder'),
]
