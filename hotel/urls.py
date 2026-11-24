from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth
from django.urls import path

from . import views
from .models import (
    Amenity,
    Booking,
    BookingGuest,
    Cleaning,
    Payment,
    Review,
    Room,
    RoomAmenity,
    RoomType,
    Tariff,
)

admin.site.register([
    RoomType, Amenity, Room, RoomAmenity, Tariff,
    Booking, BookingGuest, Payment, Cleaning, Review,
])

admin.site.site_header = 'ОТЕЛЬ ВОЛГА — управление'
admin.site.site_title = 'ОТЕЛЬ ВОЛГА'
admin.site.index_title = 'Панель администрирования гостиницы'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.catalog, name='catalog'),
    path('rooms/', views.catalog, name='room_list'),
    path('search/', views.catalog, name='search'),
    path('rooms/<int:pk>/', views.room_detail, name='room_detail'),
    path('rooms/<int:pk>/book/', views.book, name='book'),
    path('rooms/<int:pk>/quote/', views.quote, name='quote'),
    path('api/calc-price/', views.api_calc_price, name='api_calc_price'),
    path('my-bookings/', views.my_bookings, name='my_bookings'),
    path('bookings/<int:pk>/', views.booking_detail, name='booking_detail'),
    path('bookings/<int:pk>/voucher/', views.voucher, name='voucher'),
    path('bookings/<int:pk>/cancel/', views.cancel, name='cancel'),
    path('bookings/<int:pk>/review/', views.review_add, name='review'),
    path('reviews/add/', views.review_add, name='review_add'),
    path('reviews/<int:pk>/edit/', views.review_edit, name='review_edit'),
    path('reviews/<int:pk>/delete/', views.review_delete, name='review_delete'),
    path('about/', views.about, name='about'),
    path('login/', views.RateLimitedLoginView.as_view(), name='login'),
    path('logout/', auth.LogoutView.as_view(), name='logout'),
    path('register/', views.register, name='register'),
    path(
        'password-change/',
        auth.PasswordChangeView.as_view(
            template_name='form.html',
            success_url='/my-bookings/',
            extra_context={'title': 'Смена пароля'},
        ),
        name='password_change',
    ),
    path('staff/bookings/', views.staff_bookings, name='staff_bookings'),
    path('staff/checkin/', views.staff_checkin, name='staff_checkin'),
    path('staff/checkout/<int:pk>/', views.staff_checkout, name='staff_checkout'),
    path('staff/cleaning/', views.cleaning, name='cleaning'),
    path('manager/stats/', views.stats, name='stats'),
    path('manager/tariffs/', views.manager_tariffs, name='manager_tariffs'),
    path('manager/export-csv/', views.export_csv, name='export_csv'),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
