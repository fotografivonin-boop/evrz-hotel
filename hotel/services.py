import logging
from datetime import timedelta
from decimal import Decimal
from smtplib import SMTPException

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import Booking, Cleaning, Tariff

logger = logging.getLogger('hotel')

ACTIVE_BOOKING_STATUSES = ('new', 'confirmed', 'checked_in')


class HotelBookingError(Exception):
    """Пользовательское исключение бизнес-логики бронирования."""


def is_room_available(room, start_date, end_date, exclude_booking_id=None):
    """
    Проверяет доступность номера на интервал [start_date, end_date).
    Строгое неравенство (< и >) разрешает заезд в день выезда прошлого гостя.
    """
    qs = Booking.objects.filter(
        room=room,
        status__in=ACTIVE_BOOKING_STATUSES,
        check_in_date__lt=end_date,
        check_out_date__gt=start_date,
    )
    if exclude_booking_id:
        qs = qs.exclude(pk=exclude_booking_id)
    return not qs.exists()


def calculate_stay_price(room, start_date, end_date):
    """
    Считает итоговую стоимость проживания циклом по каждой ночи отдельно
    с учётом активного сезонного тарифа (Tariff), иначе берёт base_price.
    Возвращает кортеж (total_price: Decimal, tariff_names: list[str]).
    """
    if end_date <= start_date:
        raise HotelBookingError('Дата выезда должна быть позже даты заезда.')

    total = Decimal('0.00')
    applied_tariffs = []
    current_day = start_date

    while current_day < end_date:
        tariff = (
            Tariff.objects.filter(
                room_type=room.room_type,
                is_active=True,
                start_date__lte=current_day,
                end_date__gte=current_day,
            )
            .order_by('-start_date', '-pk')
            .first()
        )
        if tariff:
            total += tariff.price_per_night
            if tariff.name not in applied_tariffs:
                applied_tariffs.append(tariff.name)
        else:
            total += room.room_type.base_price
        current_day += timedelta(days=1)

    return total, applied_tariffs


def send_booking_email(subject, message, recipient_email):
    """Отправляет email через почтовый бэкенд Django с перехватом SMTP/сетевых ошибок."""
    if not recipient_email:
        return False
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@hotel-volga.local'),
            recipient_list=[recipient_email],
            fail_silently=False,
        )
        return True
    except (SMTPException, OSError) as exc:
        logger.error('Email send failed to %s: %s', recipient_email, exc)
        return False


def create_checkout_cleaning(booking, staff_name='Дежурная горничная'):
    """Автоматически создаёт задачу генеральной уборки после выезда гостя."""
    return Cleaning.objects.create(
        room=booking.room,
        scheduled_date=timezone.now(),
        cleaning_type='checkout',
        assigned_staff=staff_name,
        status='scheduled',
        notes=f'Автоматическая уборка после выезда по брони №{booking.pk}',
    )
