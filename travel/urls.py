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
    path('cards/', views.card_templates, name='card_templates'),
    path('cards/<int:pk>/delete/', views.card_template_delete, name='card_template_delete'),
    path('api/plan/<int:plan_pk>/add/', views.api_add_item, name='api_add_item'),
    path('api/plan/<int:plan_pk>/remove/<int:item_pk>/', views.api_remove_item, name='api_remove_item'),
    path('api/plan/<int:plan_pk>/reorder/', views.api_reorder, name='api_reorder'),
]
