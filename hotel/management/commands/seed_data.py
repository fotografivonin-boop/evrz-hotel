from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw

from hotel.models import (
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


def _generate_placeholder_images():
    """Create lightweight local placeholder images if static room photos are missing."""
    img_dir = Path(settings.BASE_DIR) / 'hotel' / 'static' / 'images'
    img_dir.mkdir(parents=True, exist_ok=True)
    specs = [
        ('single.webp', (480, 270), (226, 234, 248), 'Одноместный номер'),
        ('double.webp', (480, 270), (219, 234, 254), 'Стандарт двухместный'),
        ('twin.webp', (480, 270), (224, 231, 255), 'Стандарт Твин'),
        ('suite.webp', (480, 270), (254, 243, 199), 'Люкс и Апартаменты'),
    ]
    for filename, size, bg, _label in specs:
        target = img_dir / filename
        if not target.exists():
            img = Image.new('RGB', size, bg)
            draw = ImageDraw.Draw(img)
            draw.rectangle([20, 20, size[0] - 20, size[1] - 20], outline=(30, 58, 138), width=3)
            draw.rectangle([50, 140, size[0] - 50, size[1] - 40], fill=(255, 255, 255), outline=(148, 163, 184))
            img.save(target, format='WEBP', quality=85)


class Command(BaseCommand):
    help = 'Наполняет базу данных демонстрационными данными EVRZ Hotel'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Очистить таблицы отеля перед заполнением',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        _generate_placeholder_images()

        if options['reset']:
            Review.objects.all().delete()
            Cleaning.objects.all().delete()
            Payment.objects.all().delete()
            BookingGuest.objects.all().delete()
            Booking.objects.all().delete()
            Tariff.objects.all().delete()
            RoomAmenity.objects.all().delete()
            Room.objects.all().delete()
            Amenity.objects.all().delete()
            RoomType.objects.all().delete()

        # 1. Пользователи (4 роли)
        users_spec = [
            ('admin_manager', 'manager@evrz-hotel.ru', 'ManagerPass123!', True, True, 'Андрей', 'Смирнов'),
            ('reception_anna', 'reception@evrz-hotel.ru', 'StaffPass123!', True, False, 'Анна', 'Кузнецова'),
            ('ivonin_ad', 'ivonin@mail.ru', 'ClientPass123!', False, False, 'Александр', 'Ивонин'),
            ('petrov_iv', 'petrov@yandex.ru', 'ClientPass123!', False, False, 'Иван', 'Петров'),
            ('sokolova_ea', 'sokolova@mail.ru', 'ClientPass123!', False, False, 'Елена', 'Соколова'),
            ('morozov_ds', 'morozov@bk.ru', 'ClientPass123!', False, False, 'Дмитрий', 'Морозов'),
            ('volkova_ma', 'volkova@inbox.ru', 'ClientPass123!', False, False, 'Мария', 'Волкова'),
            ('lebedev_ka', 'lebedev@yandex.ru', 'ClientPass123!', False, False, 'Кирилл', 'Лебедев'),
            ('novikov_av', 'novikov@mail.ru', 'ClientPass123!', False, False, 'Алексей', 'Новиков'),
            ('kozlov_ps', 'kozlov@list.ru', 'ClientPass123!', False, False, 'Павел', 'Козлов'),
            ('orlova_tv', 'orlova@yandex.ru', 'ClientPass123!', False, False, 'Татьяна', 'Орлова'),
            ('tarasov_mn', 'tarasov@mail.ru', 'ClientPass123!', False, False, 'Максим', 'Тарасов'),
        ]
        users = {}
        for username, email, pwd, is_staff, is_super, first, last in users_spec:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'email': email,
                    'is_staff': is_staff,
                    'is_superuser': is_super,
                    'first_name': first,
                    'last_name': last,
                },
            )
            if created or options['reset']:
                user.set_password(pwd)
                user.is_staff = is_staff
                user.is_superuser = is_super
                user.save()
            users[username] = user

        # 2. Типы номеров (10)
        room_types_spec = [
            ('Эконом одноместный', Decimal('2500.00'), 1, Decimal('14.5'), 'Уютный одноместный номер с рабочей зоной и видом во двор.'),
            ('Стандарт двухместный (1 кровать)', Decimal('3600.00'), 2, Decimal('19.0'), 'Классический номер с большой двуспальной кроватью Queen Size.'),
            ('Стандарт Твин (2 кровати)', Decimal('3700.00'), 2, Decimal('20.5'), 'Светлый номер с двумя раздельными кроватями и телевизором Smart TV.'),
            ('Комфорт плюс', Decimal('4800.00'), 3, Decimal('25.0'), 'Просторный номер с зоной отдыха и дополнительным спальным местом.'),
            ('Студия с мини-кухней', Decimal('5400.00'), 3, Decimal('28.5'), 'Удобная студия для длительного проживания с оборудованной мини-кухней.'),
            ('Полулюкс панорамный', Decimal('6500.00'), 3, Decimal('33.0'), 'Номер повышенной комфортности с панорамными окнами на город.'),
            ('Семейный двухкомнатный', Decimal('7400.00'), 4, Decimal('40.0'), 'Две изолированные комнаты для комфортного отдыха семьи с детьми.'),
            ('Бизнес с кабинетом', Decimal('8200.00'), 2, Decimal('36.0'), 'Деловой номер с выделенным кабинетом, кофемашиной и сейфом.'),
            ('Люкс двухкомнатный', Decimal('9800.00'), 4, Decimal('48.0'), 'Премиальный двухкомнатный люкс с гостиной, халатами и завтраком.'),
            ('Апартаменты Представительские', Decimal('12500.00'), 5, Decimal('65.0'), 'Просторные представительские апартаменты на верхнем этаже отеля.'),
        ]
        room_types = []
        for name, base_price, max_guests, area, desc in room_types_spec:
            rt, _ = RoomType.objects.get_or_create(
                name=name,
                defaults={
                    'base_price': base_price,
                    'max_guests': max_guests,
                    'area': area,
                    'description': desc,
                },
            )
            room_types.append(rt)

        # 3. Удобства (12)
        amenities_spec = [
            ('Бесплатный Wi-Fi', 'Интернет и связь', 'wifi'),
            ('Кондиционер', 'Климат', 'ac'),
            ('Телевизор Smart TV', 'Мультимедиа', 'tv'),
            ('Мини-холодильник', 'Кухня', 'fridge'),
            ('Электронный сейф', 'Безопасность', 'safe'),
            ('Фен и туалетные принадлежности', 'Ванная', 'bath'),
            ('Чайная станция (чайник, чашки)', 'Кухня', 'tea'),
            ('Завтрак шведский стол', 'Питание', 'breakfast'),
            ('Вид на внутренний парк', 'Вид из окна', 'park'),
            ('Халаты и тапочки', 'Ванная', 'robe'),
            ('Кофемашина капсульная', 'Кухня', 'coffee'),
            ('Рабочий письменный стол', 'Мебель', 'desk'),
        ]
        amenities = []
        for name, category, icon_code in amenities_spec:
            am, _ = Amenity.objects.get_or_create(
                name=name,
                defaults={'category': category, 'icon_code': icon_code},
            )
            amenities.append(am)

        # 4. Номера (35: 5 этажей по 7 комнат, включая 101, 102, 201, 202)
        rooms = []
        for floor in range(1, 6):
            for idx in range(1, 8):
                room_num = f'{floor}0{idx}'
                rt_index = min(9, (floor - 1) * 2 + (idx - 1) // 4)
                if room_num == '101':
                    rt = room_types[0]
                elif room_num == '102':
                    rt = room_types[1]
                elif room_num == '201':
                    rt = room_types[2]
                elif room_num == '202':
                    rt = room_types[3]
                else:
                    rt = room_types[rt_index]
                room, _ = Room.objects.get_or_create(
                    room_number=room_num,
                    defaults={
                        'room_type': rt,
                        'floor': floor,
                        'is_active': True,
                        'description': f'Номер {room_num} на {floor} этаже. {rt.description}',
                    },
                )
                rooms.append(room)

        # 5. Связки RoomAmenity (~104 штуки)
        if RoomAmenity.objects.count() < 100:
            for idx, room in enumerate(rooms):
                count = 3 if idx < 31 else 2
                if idx < 4:
                    count = 4
                for a_i in range(count):
                    am = amenities[(idx + a_i) % len(amenities)]
                    RoomAmenity.objects.get_or_create(
                        room=room,
                        amenity=am,
                        defaults={'is_main': a_i < 2, 'note': ''},
                    )

        # 6. Сезонные тарифы (12)
        if Tariff.objects.count() == 0:
            tariffs_spec = [
                (0, 'Летний высокий сезон', date(2026, 6, 1), date(2026, 8, 31), Decimal('3100.00')),
                (1, 'Летний высокий сезон', date(2026, 6, 1), date(2026, 8, 31), Decimal('4400.00')),
                (2, 'Летний высокий сезон', date(2026, 6, 1), date(2026, 8, 31), Decimal('4500.00')),
                (3, 'Летний высокий сезон', date(2026, 6, 1), date(2026, 8, 31), Decimal('5800.00')),
                (8, 'Летний высокий сезон', date(2026, 6, 1), date(2026, 8, 31), Decimal('11200.00')),
                (0, 'Осеннее межсезонье', date(2026, 10, 1), date(2026, 12, 20), Decimal('2300.00')),
                (1, 'Осенний тариф', date(2026, 10, 1), date(2026, 12, 20), Decimal('3400.00')),
                (2, 'Осенний тариф', date(2026, 10, 1), date(2026, 12, 20), Decimal('3500.00')),
                (3, 'Осенний тариф', date(2026, 10, 1), date(2026, 12, 20), Decimal('4500.00')),
                (1, 'Новогодний сезон', date(2026, 12, 25), date(2027, 1, 10), Decimal('4900.00')),
                (5, 'Новогодний сезон', date(2026, 12, 25), date(2027, 1, 10), Decimal('8200.00')),
                (8, 'Новогодний сезон', date(2026, 12, 25), date(2027, 1, 10), Decimal('12900.00')),
            ]
            for rt_idx, t_name, d_start, d_end, t_price in tariffs_spec:
                Tariff.objects.create(
                    room_type=room_types[rt_idx],
                    name=t_name,
                    start_date=d_start,
                    end_date=d_end,
                    price_per_night=t_price,
                    is_active=True,
                )

        # 7. Бронирования (32 без пересечения дат), 36 гостей, 32 оплаты
        if Booking.objects.count() == 0:
            client_names = [
                'petrov_iv', 'sokolova_ea', 'morozov_ds', 'volkova_ma',
                'lebedev_ka', 'novikov_av', 'kozlov_ps', 'orlova_tv',
                'tarasov_mn', 'ivonin_ad',
            ]
            statuses = ['checked_out', 'checked_in', 'confirmed', 'new', 'cancelled']
            methods = ['card_online', 'cash_desk', 'pos_desk']
            base_day = date(2026, 11, 2)
            created_bookings = []

            for i in range(32):
                room = rooms[i % len(rooms)]
                user = users[client_names[i % len(client_names)]]
                start = base_day + timedelta(days=i * 2)
                nights = 2 + (i % 4)
                end = start + timedelta(days=nights)
                status = statuses[i % len(statuses)]
                if i == 0:
                    user = users['petrov_iv']
                    status = 'checked_out'
                elif i == 9:
                    user = users['ivonin_ad']
                    status = 'confirmed'
                    start = date(2026, 12, 10)
                    end = date(2026, 12, 13)
                    nights = 3
                elif i == 19:
                    user = users['ivonin_ad']
                    status = 'checked_out'
                    start = date(2026, 11, 10)
                    end = date(2026, 11, 12)
                    nights = 2

                total = room.room_type.base_price * nights
                booking = Booking.objects.create(
                    user=user,
                    room=room,
                    check_in_date=start,
                    check_out_date=end,
                    nights_count=nights,
                    total_price=total,
                    status=status,
                    contact_name=f'{user.last_name} {user.first_name}',
                    contact_phone=f'+7916100{i:04d}',
                    contact_email=user.email,
                    comment='Просим подготовить номер к 14:00' if i % 3 == 0 else '',
                )
                created_bookings.append(booking)

                BookingGuest.objects.create(
                    booking=booking,
                    full_name=f'{user.last_name} {user.first_name} Сергеевич',
                    birth_date=date(1988 + (i % 12), 1 + (i % 12), 10 + (i % 15)),
                    document_number=f'45 18 {100000 + i}',
                    phone=f'+7916100{i:04d}',
                )
                # Доп. гости (еще 4 гостя = 36 всего)
                if i < 4 and room.room_type.max_guests >= 2:
                    BookingGuest.objects.create(
                        booking=booking,
                        full_name=f'Сопровождающий Гость {i + 1}',
                        birth_date=date(1992 + i, 5, 14),
                        document_number=f'45 20 {200000 + i}',
                        phone=f'+7916200{i:04d}',
                    )

                pay_status = 'paid' if status in ('confirmed', 'checked_in', 'checked_out') else (
                    'refunded' if status == 'cancelled' else 'pending'
                )
                Payment.objects.create(
                    booking=booking,
                    amount=total,
                    payment_method=methods[i % 3],
                    status=pay_status,
                    paid_at=timezone.now() - timedelta(days=32 - i) if pay_status == 'paid' else None,
                    receipt_number=f'EVRZ-2026-{i + 1:04d}',
                )

            # 8. Уборки (15)
            staff_list = ['Смирнова О.В.', 'Васильева Н.А.', 'Петрова И.С.', 'Федорова М.П.']
            c_types = ['checkout', 'daily', 'extra']
            c_statuses = ['completed', 'in_progress', 'scheduled']
            for i in range(15):
                Cleaning.objects.create(
                    room=rooms[i],
                    scheduled_date=timezone.make_aware(datetime(2026, 11, 10 + (i % 14), 12, 0)),
                    cleaning_type=c_types[i % 3],
                    assigned_staff=staff_list[i % len(staff_list)],
                    status=c_statuses[i % 3],
                    notes='Смена белья и влажная уборка' if i % 2 == 0 else 'Проверка мини-бара',
                )

            # 9. Отзывы (12)
            review_texts = [
                'Чистый и тихий номер, быстрое заселение на стойке.',
                'Удобное расположение отеля, отличный Wi-Fi для работы.',
                'Очень комфортная кровать и вкусный завтрак.',
                'Понравился вежливый персонал и понятный расчет цены на сайте.',
                'Хороший номер за свои деньги, все соответствует фотографиям.',
                'Светлая комната, свежий ремонт, уборка каждый день.',
            ]
            review_candidates = [b for b in created_bookings if b.status == 'checked_out']
            if len(review_candidates) < 12:
                extra = [b for b in created_bookings if b not in review_candidates]
                review_candidates.extend(extra[: 12 - len(review_candidates)])
            for idx, b in enumerate(review_candidates[:12]):
                Review.objects.create(
                    booking=b,
                    room=b.room,
                    user=b.user,
                    rating=5 if idx % 3 != 0 else 4,
                    text=review_texts[idx % len(review_texts)],
                )

        self.stdout.write(self.style.SUCCESS(
            f'Seed OK: types={RoomType.objects.count()}, amenities={Amenity.objects.count()}, '
            f'rooms={Room.objects.count()}, room_amenities={RoomAmenity.objects.count()}, '
            f'tariffs={Tariff.objects.count()}, bookings={Booking.objects.count()}, '
            f'guests={BookingGuest.objects.count()}, payments={Payment.objects.count()}, '
            f'cleanings={Cleaning.objects.count()}, reviews={Review.objects.count()}'
        ))
