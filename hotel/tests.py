import io
from datetime import date, timedelta
from decimal import Decimal
from smtplib import SMTPException
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase
from PIL import Image

from .models import (
    Amenity,
    Booking,
    Cleaning,
    Payment,
    Review,
    Room,
    RoomAmenity,
    RoomType,
    Tariff,
)
from .services import send_booking_email


class ExceptionHandlingTests(TestCase):
    """5 обязательных негативных автотестов (Занятие 16) + проверки бизнес-логики и безопасности."""

    def setUp(self):
        cache.clear()
        self.client_user = User.objects.create_user(
            username='ivonin_ad',
            email='ivonin@mail.ru',
            password='ClientPass123!',
        )
        self.other_user = User.objects.create_user(
            username='petrov_iv',
            email='petrov@yandex.ru',
            password='ClientPass123!',
        )
        self.reception_user = User.objects.create_user(
            username='reception_anna',
            email='reception@hotel-volga.ru',
            password='StaffPass123!',
            is_staff=True,
            is_superuser=False,
        )
        self.manager_user = User.objects.create_superuser(
            username='admin_manager',
            email='manager@hotel-volga.ru',
            password='ManagerPass123!',
        )

        self.rt_single = RoomType.objects.create(
            name='Эконом одноместный',
            base_price=Decimal('2500.00'),
            max_guests=1,
            area=Decimal('15.0'),
        )
        self.rt_std = RoomType.objects.create(
            name='Стандарт двухместный',
            base_price=Decimal('3600.00'),
            max_guests=2,
            area=Decimal('20.0'),
        )
        self.amenity_wifi = Amenity.objects.create(name='Бесплатный Wi-Fi', category='Интернет', icon_code='wifi')
        self.room_101 = Room.objects.create(
            room_number='101',
            room_type=self.rt_single,
            floor=1,
            is_active=True,
            description='Тихий одноместный номер',
        )
        self.room = Room.objects.create(
            room_number='102',
            room_type=self.rt_std,
            floor=1,
            is_active=True,
            description='Светлый стандартный номер',
        )
        RoomAmenity.objects.create(room=self.room, amenity=self.amenity_wifi)

        today = date.today()
        self.other_booking = Booking.objects.create(
            user=self.other_user,
            room=self.room,
            check_in_date=today + timedelta(days=5),
            check_out_date=today + timedelta(days=10),
            nights_count=5,
            total_price=Decimal('18000.00'),
            status='confirmed',
        )

    def test_1_missing_room_returns_404(self):
        resp = self.client.get('/rooms/99999/')
        self.assertEqual(resp.status_code, 404)

    def test_2_foreign_booking_returns_403(self):
        self.client.force_login(self.client_user)
        resp = self.client.get(f'/bookings/{self.other_booking.id}/')
        self.assertEqual(resp.status_code, 403)
        resp_voucher = self.client.get(f'/bookings/{self.other_booking.id}/voucher/')
        self.assertEqual(resp_voucher.status_code, 403)

    def test_3_invalid_booking_form_no_save(self):
        self.client.force_login(self.client_user)
        count_before = Booking.objects.count()
        today = date.today()
        resp = self.client.post(f'/rooms/{self.room.id}/book/', {
            'check_in_date': (today + timedelta(days=20)).isoformat(),
            'check_out_date': (today + timedelta(days=18)).isoformat(),
            'guests_count': 1,
            'full_name': 'Ивонин Александр',
            'birth_date': '2004-05-10',
            'document_number': '45 19 123456',
            'phone': '+79161234567',
            'email': 'ivonin@mail.ru',
            'payment_method': 'card_online',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Booking.objects.count(), count_before)
        self.assertContains(resp, 'Дата выезда должна быть позже даты заезда')

    def test_4_atomic_rollback_on_mid_error(self):
        count_before = Booking.objects.count()
        today = date.today()
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                Booking.objects.create(
                    user=self.client_user,
                    room=self.room,
                    check_in_date=today + timedelta(days=25),
                    check_out_date=today + timedelta(days=27),
                    nights_count=2,
                    total_price=Decimal('7200.00'),
                )
                raise RuntimeError('Сбой при сохранении гостя')
        self.assertEqual(Booking.objects.count(), count_before)

    def test_5_empty_stats_and_csv_no_crash(self):
        Booking.objects.all().delete()
        self.client.force_login(self.manager_user)
        resp_stats = self.client.get('/manager/stats/')
        resp_csv = self.client.get('/manager/export-csv/')
        self.assertEqual(resp_stats.status_code, 200)
        self.assertEqual(resp_csv.status_code, 200)
        self.assertIn('ID брони;Номер;Категория', resp_csv.content.decode('utf-8-sig'))


class HotelBusinessAndSecurityTests(TestCase):
    """Проверки исправленных багов BUG-01..BUG-09 и безопасности SEC-01..SEC-03."""

    def setUp(self):
        cache.clear()
        self.client_user = User.objects.create_user(
            username='ivonin_ad',
            email='ivonin@mail.ru',
            password='ClientPass123!',
        )
        self.reception_user = User.objects.create_user(
            username='reception_anna',
            email='reception@hotel-volga.ru',
            password='StaffPass123!',
            is_staff=True,
            is_superuser=False,
        )
        self.manager_user = User.objects.create_superuser(
            username='admin_manager',
            email='manager@hotel-volga.ru',
            password='ManagerPass123!',
        )
        self.rt_single = RoomType.objects.create(
            name='Эконом одноместный',
            base_price=Decimal('2500.00'),
            max_guests=1,
            area=Decimal('15.0'),
        )
        self.rt_std = RoomType.objects.create(
            name='Стандарт двухместный',
            base_price=Decimal('3600.00'),
            max_guests=2,
            area=Decimal('20.0'),
        )
        self.room_101 = Room.objects.create(room_number='101', room_type=self.rt_single, floor=1, is_active=True)
        self.room_102 = Room.objects.create(room_number='102', room_type=self.rt_std, floor=1, is_active=True)

    def test_bug01_catalog_invalid_dates_shows_error(self):
        resp = self.client.get('/rooms/?check_in=2026-12-20&check_out=2026-12-18')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Дата выезда должна быть позже даты заезда')

    def test_bug03_border_dates_allowed_and_overlap_blocked(self):
        today = date.today()
        d1 = today + timedelta(days=5)
        d2 = today + timedelta(days=10)
        Booking.objects.create(
            user=self.client_user,
            room=self.room_102,
            check_in_date=d1,
            check_out_date=d2,
            nights_count=5,
            total_price=Decimal('18000.00'),
            status='confirmed',
        )
        # День выезда (d2) = день заезда нового гостя -> разрешено!
        resp_ok = self.client.get(
            f'/api/calc-price/?room={self.room_102.pk}&in={d2.isoformat()}&out={(d2 + timedelta(days=3)).isoformat()}'
        )
        self.assertEqual(resp_ok.status_code, 200)
        self.assertTrue(resp_ok.json()['available'])

        # Пересечение (d1+2 .. d2+1) -> занято!
        resp_busy = self.client.get(
            f'/api/calc-price/?room={self.room_102.pk}&in={(d1 + timedelta(days=2)).isoformat()}&out={(d2 + timedelta(days=1)).isoformat()}'
        )
        self.assertEqual(resp_busy.status_code, 200)
        self.assertFalse(resp_busy.json()['available'])

    def test_bug04_calc_price_across_season_boundary(self):
        today = date.today()
        d_start = today + timedelta(days=10)
        d_mid = today + timedelta(days=12)  # 2 ночи по тарифу, 1 ночь по базовой
        Tariff.objects.create(
            room_type=self.rt_std,
            name='Осенний тариф',
            start_date=d_start,
            end_date=d_mid - timedelta(days=1),
            price_per_night=Decimal('3400.00'),
            is_active=True,
        )
        resp = self.client.get(
            f'/api/calc-price/?room={self.room_102.pk}&in={d_start.isoformat()}&out={(d_mid + timedelta(days=1)).isoformat()}'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['nights'], 3)
        self.assertEqual(Decimal(data['total']), Decimal('10400.00'))  # 3400 + 3400 + 3600

    def test_bug05_max_guests_enforced(self):
        self.client.force_login(self.client_user)
        today = date.today()
        resp = self.client.post(f'/rooms/{self.room_101.pk}/book/', {
            'check_in_date': (today + timedelta(days=15)).isoformat(),
            'check_out_date': (today + timedelta(days=17)).isoformat(),
            'guests_count': 2,
            'full_name': 'Ивонин Александр',
            'birth_date': '2004-05-10',
            'document_number': '45 19 123456',
            'phone': '+79161234567',
            'email': 'ivonin@mail.ru',
            'payment_method': 'card_online',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Превышена максимальная вместимость номера')
        self.assertEqual(Booking.objects.count(), 0)

    def test_bug06_checkout_creates_cleaning(self):
        today = date.today()
        booking = Booking.objects.create(
            user=self.client_user,
            room=self.room_102,
            check_in_date=today - timedelta(days=2),
            check_out_date=today,
            nights_count=2,
            total_price=Decimal('7200.00'),
            status='checked_in',
        )
        self.client.force_login(self.reception_user)
        resp = self.client.post(f'/staff/checkout/{booking.pk}/')
        self.assertEqual(resp.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'checked_out')
        self.assertEqual(Cleaning.objects.filter(room=self.room_102, cleaning_type='checkout').count(), 1)

    def test_sec01_login_rate_limit(self):
        for _ in range(5):
            resp = self.client.post('/login/', {'username': 'ivonin_ad', 'password': 'WrongPassword!'})
        self.assertEqual(resp.status_code, 429)
        self.assertContains(resp, 'заблокирован', status_code=429)

    def test_sec02_fake_jpg_and_oversized_photo_rejected(self):
        today = date.today()
        booking = Booking.objects.create(
            user=self.client_user,
            room=self.room_102,
            check_in_date=today - timedelta(days=4),
            check_out_date=today - timedelta(days=1),
            nights_count=3,
            total_price=Decimal('10800.00'),
            status='checked_out',
        )
        self.client.force_login(self.client_user)

        fake_jpg = SimpleUploadedFile('fake.jpg', b'this is plain text not jpeg', content_type='image/jpeg')
        resp_fake = self.client.post('/reviews/add/', {
            'booking_id': booking.pk,
            'rating': 5,
            'text': 'Проверка поддельного файла',
            'photo': fake_jpg,
        })
        self.assertEqual(resp_fake.status_code, 200)
        self.assertEqual(Review.objects.count(), 0)
        self.assertContains(resp_fake, 'картинкой')

        # Валидная PNG-картинка должна пройти
        buf = io.BytesIO()
        Image.new('RGB', (40, 40), (30, 58, 138)).save(buf, format='PNG')
        valid_png = SimpleUploadedFile('ok.png', buf.getvalue(), content_type='image/png')
        resp_ok = self.client.post('/reviews/add/', {
            'booking_id': booking.pk,
            'rating': 5,
            'text': 'Отличный номер и быстрый сервис',
            'photo': valid_png,
        })
        self.assertEqual(resp_ok.status_code, 302)
        self.assertEqual(Review.objects.count(), 1)

    def test_role_permissions_reception_cannot_access_manager(self):
        self.client.force_login(self.reception_user)
        self.assertEqual(self.client.get('/staff/bookings/').status_code, 200)
        self.assertEqual(self.client.get('/manager/stats/').status_code, 403)
        self.assertEqual(self.client.get('/manager/export-csv/').status_code, 403)

    def test_safe_mail_handles_smtp_exception(self):
        with patch('hotel.services.send_mail', side_effect=SMTPException('SMTP down')):
            ok = send_booking_email('Test', 'Body', 'ivonin@mail.ru')
        self.assertFalse(ok)
