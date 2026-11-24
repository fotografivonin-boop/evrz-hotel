from django.urls import path
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth
from . import views
from .models import (
    RoomType, Amenity, Room, RoomAmenity, Tariff,
    Booking, BookingGuest, Payment, Cleaning, Review,
)

admin.site.register([
    RoomType, Amenity, Room, RoomAmenity, Tariff,
    Booking, BookingGuest, Payment, Cleaning, Review,
])

admin.site.site_header = 'EVRZ Hotel — управление'
admin.site.site_title = 'EVRZ Hotel'
admin.site.index_title = 'Управление гостиницей'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.catalog, name='catalog'),
    path('search/', views.catalog, name='search'),
    path('rooms/<int:pk>/', views.room_detail, name='room_detail'),
    path('rooms/<int:pk>/book/', views.book, name='book'),
    path('rooms/<int:pk>/quote/', views.quote, name='quote'),
    path('my-bookings/', views.my_bookings, name='my_bookings'),
    path('bookings/<int:pk>/voucher/', views.voucher, name='voucher'),
    path('bookings/<int:pk>/cancel/', views.cancel, name='cancel'),
    path('bookings/<int:pk>/review/', views.review, name='review'),
    path('about/', views.about, name='about'),
    path('login/', auth.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth.LogoutView.as_view(), name='logout'),
    path('register/', views.register, name='register'),
    path(
        'password-change/',
        auth.PasswordChangeView.as_view(
            template_name='form.html', success_url='/my-bookings/'
        ),
        name='password_change',
    ),
    path('staff/bookings/', views.staff_bookings, name='staff_bookings'),
    path('staff/cleaning/', views.cleaning, name='cleaning'),
    path('manager/stats/', views.stats, name='stats'),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
