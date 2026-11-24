from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Q, F
from django.templatetags.static import static


class RoomType(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name='Название категории')
    base_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(500)],
        verbose_name="Базовая цена за сутки (руб.)"
    )
    max_guests = models.PositiveSmallIntegerField(
        default=2,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        verbose_name="Максимальная вместимость гостей"
    )
    area = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        validators=[MinValueValidator(8.0)],
        verbose_name="Площадь номера (кв. м)"
    )
    description = models.TextField(blank=True, verbose_name='Описание категории')

    class Meta:
        verbose_name = "Тип номера"
        verbose_name_plural = "Типы номеров"
        ordering = ["base_price", "name"]
        constraints = [
            models.CheckConstraint(check=Q(base_price__gt=0), name='roomtype_base_price_positive'),
            models.CheckConstraint(check=Q(max_guests__gte=1), name='roomtype_max_guests_min_1'),
        ]

    def __str__(self):
        return f"{self.name} (до {self.max_guests} чел., {self.base_price} руб.)"


class Amenity(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name='Название удобства')
    category = models.CharField(max_length=50, default='Общие', verbose_name='Категория удобства')
    icon_code = models.CharField(max_length=50, blank=True, verbose_name='Код иконки')

    class Meta:
        verbose_name = "Удобство номера"
        verbose_name_plural = "Удобства номеров"
        ordering = ["category", "name"]

    def __str__(self):
        return self.name


class Room(models.Model):
    room_number = models.CharField(max_length=10, unique=True, verbose_name='Номер комнаты')
    room_type = models.ForeignKey(RoomType, on_delete=models.PROTECT, related_name='rooms', verbose_name='Тип номера')
    floor = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(30)],
        verbose_name="Этаж"
    )
    amenities = models.ManyToManyField(
        Amenity,
        through="RoomAmenity",
        related_name="rooms",
        blank=True,
        verbose_name="Удобства в номере"
    )
    image = models.ImageField(upload_to='rooms_photos/', blank=True, null=True, verbose_name='Фотография номера')
    is_active = models.BooleanField(default=True, verbose_name='Доступен для бронирования')
    description = models.TextField(blank=True, verbose_name='Особенности номера')

    class Meta:
        verbose_name = "Номер"
        verbose_name_plural = "Номера"
        ordering = ["floor", "room_number"]
        constraints = [
            models.CheckConstraint(check=Q(floor__gte=1), name='room_floor_min_1'),
        ]

    @property
    def photo_note(self):
        if self.image:
            return ''
        return 'Пример интерьера'

    @property
    def photo_detail_note(self):
        if self.image:
            return ''
        return 'Пример интерьера. Фотография конкретного номера пока не добавлена.'

    @property
    def photo_url(self):
        if self.image:
            return self.image.url

        if self.room_type.max_guests == 1:
            photo = 'single.webp'
        elif 'твин' in self.room_type.name.lower():
            photo = 'twin.webp'
        elif self.room_type.base_price >= 6000:
            photo = 'suite.webp'
        else:
            photo = 'double.webp'
        return static('images/' + photo)

    def __str__(self):
        return f"Номер {self.room_number} ({self.room_type.name}, {self.floor} этаж)"


class RoomAmenity(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='room_amenities', verbose_name='Номер')
    amenity = models.ForeignKey(
        Amenity,
        on_delete=models.CASCADE,
        related_name="amenity_rooms",
        verbose_name="Удобство"
    )
    is_main = models.BooleanField(default=True, verbose_name='Выводить на главной карточке')
    note = models.CharField(max_length=100, blank=True, verbose_name='Примечание к удобству')

    class Meta:
        verbose_name = "Удобство в конкретном номере"
        verbose_name_plural = "Связь номеров и удобств"
        ordering = ["room", "amenity"]
        constraints = [
            models.UniqueConstraint(
                fields=["room", "amenity"],
                name="unique_room_amenity_pair"
            )
        ]

    def __str__(self):
        return f"Номер {self.room.room_number} - {self.amenity.name}"


class Tariff(models.Model):
    room_type = models.ForeignKey(RoomType, on_delete=models.CASCADE, related_name='tariffs', verbose_name='Тип номера')
    name = models.CharField(max_length=120, verbose_name='Название сезонного тарифа')
    start_date = models.DateField(verbose_name='Дата начала сезона')
    end_date = models.DateField(verbose_name='Дата окончания сезона')
    price_per_night = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(500)],
        verbose_name="Цена за ночь в сезон (руб.)"
    )
    is_active = models.BooleanField(default=True, verbose_name='Тариф активен')

    class Meta:
        verbose_name = "Сезонный тариф"
        verbose_name_plural = "Сезонные тарифы"
        ordering = ["-start_date", "room_type"]
        constraints = [
            models.CheckConstraint(
                check=Q(end_date__gte=F("start_date")),
                name="tariff_end_date_gte_start_date"
            ),
            models.CheckConstraint(check=Q(price_per_night__gt=0), name='tariff_price_positive'),
        ]

    def __str__(self):
        return f"{self.name} ({self.room_type.name}): {self.price_per_night} руб."


class Booking(models.Model):
    contact_name = models.CharField(max_length=150, blank=True, verbose_name="Имя контактного лица")
    contact_phone = models.CharField(max_length=20, blank=True, verbose_name="Контактный телефон")
    contact_email = models.EmailField(blank=True, verbose_name="Электронная почта")
    STATUS_CHOICES = [
        ("new", "Создана (Ожидает оплаты)"),
        ("confirmed", "Подтверждена"),
        ("checked_in", "Заселен"),
        ("checked_out", "Выехал (Завершена)"),
        ("cancelled", "Отменена"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bookings', verbose_name='Клиент')
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name='bookings', verbose_name='Номер')
    check_in_date = models.DateField(verbose_name='Дата заезда')
    check_out_date = models.DateField(verbose_name='Дата выезда')
    nights_count = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        verbose_name="Количество ночей"
    )
    total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Итоговая стоимость (руб.)"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new', verbose_name='Статус бронирования')
    comment = models.TextField(blank=True, verbose_name='Пожелания клиента')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата и время создания')

    class Meta:
        verbose_name = "Бронирование"
        verbose_name_plural = "Бронирования"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                check=Q(check_out_date__gt=F("check_in_date")),
                name="booking_check_out_after_check_in"
            ),
            models.CheckConstraint(check=Q(nights_count__gte=1), name='booking_nights_min_1'),
        ]

    def __str__(self):
        return f"Бронь №{self.id} - Номер {self.room.room_number} ({self.check_in_date} .. {self.check_out_date})"


class BookingGuest(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='guests', verbose_name='Бронирование')
    full_name = models.CharField(max_length=150, verbose_name='ФИО проживающего гостя')
    birth_date = models.DateField(verbose_name='Дата рождения')
    document_number = models.CharField(max_length=30, verbose_name='Серия и номер паспорта / свидетельства')
    phone = models.CharField(max_length=20, blank=True, verbose_name='Контактный телефон')

    class Meta:
        verbose_name = "Гость брони"
        verbose_name_plural = "Гости броней"
        ordering = ["booking", "full_name"]

    def __str__(self):
        return f"{self.full_name} (Бронь №{self.booking.id})"


class Payment(models.Model):
    METHOD_CHOICES = [
        ("card_online", "Банковская карта на сайте"),
        ("cash_desk", "Наличными на стойке"),
        ("pos_desk", "Терминал на стойке"),
    ]
    STATUS_CHOICES = [
        ("pending", "Ожидает оплаты"),
        ("paid", "Оплачено"),
        ("refunded", "Возврат при отмене"),
    ]

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='payments', verbose_name='Бронирование')
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(1)],
        verbose_name="Сумма платежа (руб.)"
    )
    payment_method = models.CharField(
        max_length=20,
        choices=METHOD_CHOICES,
        default="card_online",
        verbose_name="Способ оплаты"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='Статус оплаты')
    paid_at = models.DateTimeField(blank=True, null=True, verbose_name='Дата и время оплаты')
    receipt_number = models.CharField(max_length=40, unique=True, verbose_name='Номер чека / квитанции')

    class Meta:
        verbose_name = "Оплата"
        verbose_name_plural = "Оплаты"
        ordering = ["-paid_at", "-id"]
        constraints = [
            models.CheckConstraint(check=Q(amount__gt=0), name='payment_amount_positive')
        ]

    def __str__(self):
        return f"Чек {self.receipt_number} на {self.amount} руб. ({self.get_status_display()})"


class Cleaning(models.Model):
    TYPE_CHOICES = [
        ("checkout", "Генеральная после выезда"),
        ("daily", "Ежедневная текущая"),
        ("extra", "Внеплановая"),
    ]
    STATUS_CHOICES = [
        ("scheduled", "Назначена"),
        ("in_progress", "В процессе"),
        ("completed", "Завершена (Номер готов)"),
    ]

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='cleanings', verbose_name='Номер')
    scheduled_date = models.DateTimeField(verbose_name='Дата и время уборки')
    cleaning_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='checkout', verbose_name='Тип уборки')
    assigned_staff = models.CharField(max_length=120, verbose_name='ФИО горничной')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled', verbose_name='Статус уборки')
    notes = models.CharField(max_length=255, blank=True, verbose_name='Примечание по комнате')

    class Meta:
        verbose_name = "Уборка номера"
        verbose_name_plural = "График уборок"
        ordering = ["-scheduled_date"]

    def __str__(self):
        return f"Уборка номера {self.room.room_number} ({self.scheduled_date:%d.%m.%Y %H:%M})"


class Review(models.Model):
    booking = models.OneToOneField(
        Booking,
        on_delete=models.CASCADE,
        related_name="review",
        verbose_name="Завершенное бронирование"
    )
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='reviews', verbose_name='Номер')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews', verbose_name='Автор отзыва')
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name="Оценка (от 1 до 5)"
    )
    text = models.TextField(verbose_name='Текст отзыва')
    photo = models.ImageField(
        upload_to="reviews_photos/",
        blank=True,
        null=True,
        verbose_name="Прикрепленное фото гостя"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата публикации')

    class Meta:
        verbose_name = "Отзыв клиента"
        verbose_name_plural = "Отзывы клиентов"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                check=Q(rating__gte=1) & Q(rating__lte=5),
                name="review_rating_between_1_and_5"
            )
        ]

    def __str__(self):
        return f"Отзыв на номер {self.room.room_number} (Оценка: {self.rating}/5)"
