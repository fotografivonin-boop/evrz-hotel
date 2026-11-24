import logging
from datetime import date
from pathlib import Path

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from PIL import Image, UnidentifiedImageError

from .models import Booking, BookingGuest, Cleaning, Review, Tariff
from .services import is_room_available

logger = logging.getLogger('hotel')

MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5 МБ
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
ALLOWED_IMAGE_FORMATS = {'JPEG', 'PNG', 'WEBP'}


class BookingForm(forms.ModelForm):
    guests_count = forms.IntegerField(
        label='Количество гостей',
        min_value=1,
        max_value=10,
        initial=1,
        widget=forms.NumberInput(attrs={'min': 1, 'max': 10}),
    )
    full_name = forms.CharField(
        label='ФИО основного гостя',
        max_length=150,
        error_messages={'required': 'Укажите ФИО проживающего гостя.'},
    )
    phone = forms.RegexField(
        r'^\+?[0-9 ()-]{10,20}$',
        label='Контактный телефон',
        error_messages={
            'required': 'Укажите контактный телефон.',
            'invalid': 'Введите корректный номер телефона (10–20 символов).',
        },
    )
    email = forms.EmailField(
        label='Электронная почта',
        error_messages={
            'required': 'Укажите электронную почту.',
            'invalid': 'Введите корректный адрес электронной почты.',
        },
    )
    birth_date = forms.DateField(
        label='Дата рождения гостя',
        widget=forms.DateInput(attrs={'type': 'date'}),
        error_messages={'required': 'Укажите дату рождения гостя.'},
    )
    document_number = forms.CharField(
        label='Серия и номер паспорта / документа',
        max_length=30,
        error_messages={'required': 'Укажите серию и номер документа.'},
    )
    payment_method = forms.ChoiceField(
        label='Способ оплаты',
        choices=[
            ('card_online', 'Банковская карта на сайте'),
            ('cash_desk', 'Наличными на стойке'),
            ('pos_desk', 'Терминал на стойке'),
        ],
    )

    class Meta:
        model = Booking
        fields = ['check_in_date', 'check_out_date', 'comment']
        labels = {
            'check_in_date': 'Дата заезда',
            'check_out_date': 'Дата выезда',
            'comment': 'Пожелания к заселению',
        }
        widgets = {
            'check_in_date': forms.DateInput(attrs={'type': 'date'}),
            'check_out_date': forms.DateInput(attrs={'type': 'date'}),
            'comment': forms.Textarea(attrs={'rows': 3, 'maxlength': 500}),
        }
        error_messages = {
            'check_in_date': {'required': 'Выберите дату заезда.'},
            'check_out_date': {'required': 'Выберите дату выезда.'},
        }

    def __init__(self, *args, room=None, extra_guests_count=0, **kwargs):
        self.room = room
        self.extra_guests_count = extra_guests_count
        super().__init__(*args, **kwargs)
        if self.room:
            self.fields['guests_count'].widget.attrs['max'] = self.room.room_type.max_guests

    def clean(self):
        cleaned = super().clean()
        d_in = cleaned.get('check_in_date')
        d_out = cleaned.get('check_out_date')
        birth = cleaned.get('birth_date')
        guests_count = cleaned.get('guests_count') or 1

        if birth and birth > date.today():
            self.add_error('birth_date', 'Дата рождения не может быть в будущем.')

        if d_in and d_in < date.today():
            self.add_error('check_in_date', 'Дата заезда не может быть в прошлом.')

        if d_in and d_out:
            if d_out <= d_in:
                self.add_error('check_out_date', 'Дата выезда должна быть позже даты заезда.')
            elif (d_out - d_in).days > 30:
                self.add_error('check_out_date', 'Нельзя забронировать больше 30 ночей за раз.')
            elif self.room and not is_room_available(self.room, d_in, d_out):
                logger.warning('Booking overlap attempt on room_id=%s (%s..%s)', self.room.pk, d_in, d_out)
                raise forms.ValidationError(
                    'Выбранные даты уже заняты. Выберите другие дни.'
                )

        total_guests = max(guests_count, 1 + self.extra_guests_count)
        if self.room and total_guests > self.room.room_type.max_guests:
            self.add_error(
                'guests_count',
                f'Превышена максимальная вместимость номера (максимум {self.room.room_type.max_guests} чел.).',
            )

        if len(cleaned.get('comment', '')) > 500:
            self.add_error('comment', 'Комментарий не должен превышать 500 символов.')

        return cleaned


class BookingEditForm(forms.ModelForm):
    class Meta:
        model = Booking
        fields = ['comment']
        labels = {'comment': 'Пожелания к бронированию'}
        widgets = {'comment': forms.Textarea(attrs={'rows': 3, 'maxlength': 500})}


class BookingGuestForm(forms.ModelForm):
    phone = forms.RegexField(
        r'^\+?[0-9 ()-]{10,20}$',
        label='Контактный телефон',
        required=False,
        error_messages={'invalid': 'Введите корректный телефон (10–20 символов).'},
    )

    class Meta:
        model = BookingGuest
        fields = ['full_name', 'birth_date', 'document_number', 'phone']
        labels = {
            'full_name': 'ФИО гостя',
            'birth_date': 'Дата рождения',
            'document_number': 'Серия и номер документа',
            'phone': 'Телефон',
        }
        widgets = {'birth_date': forms.DateInput(attrs={'type': 'date'})}

    def clean_birth_date(self):
        birth = self.cleaned_data.get('birth_date')
        if birth and birth > date.today():
            raise forms.ValidationError('Дата рождения не может быть в будущем.')
        return birth


class RegisterForm(UserCreationForm):
    email = forms.EmailField(
        label='Электронная почта',
        error_messages={
            'required': 'Укажите электронную почту.',
            'invalid': 'Введите корректный адрес электронной почты.',
        },
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ['rating', 'text', 'photo']
        labels = {
            'rating': 'Оценка (от 1 до 5)',
            'text': 'Текст отзыва',
            'photo': 'Фотография (JPG, PNG, WEBP до 5 МБ)',
        }
        error_messages = {
            'photo': {
                'invalid_image': 'Файл не является картинкой (нужен JPG, PNG или WEBP).',
            }
        }
        widgets = {
            'rating': forms.Select(choices=[(i, f'{i} из 5') for i in range(5, 0, -1)]),
            'text': forms.Textarea(attrs={'rows': 5, 'maxlength': 2000}),
        }

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        if not photo:
            return photo

        if photo.size > MAX_UPLOAD_SIZE:
            logger.warning('Invalid upload rejected in ReviewForm: size=%s', photo.size)
            raise forms.ValidationError('Размер файла не должен превышать 5 МБ.')

        ext = Path(photo.name).suffix.lower()
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            logger.warning('Invalid upload extension rejected in ReviewForm: %s', ext)
            raise forms.ValidationError('Допускаются только изображения JPG, PNG, WEBP.')

        try:
            img = Image.open(photo)
            img.verify()
            if img.format not in ALLOWED_IMAGE_FORMATS:
                logger.warning('Invalid image format rejected in ReviewForm: %s', img.format)
                raise forms.ValidationError('Допускаются только изображения JPG, PNG, WEBP.')
            photo.seek(0)
        except forms.ValidationError:
            raise
        except (UnidentifiedImageError, OSError, Exception) as exc:
            logger.warning('Corrupted or fake image rejected in ReviewForm: %s', exc)
            raise forms.ValidationError('Файл не является картинкой (нужен JPG, PNG или WEBP).')

        return photo


class TariffForm(forms.ModelForm):
    class Meta:
        model = Tariff
        fields = ['room_type', 'name', 'start_date', 'end_date', 'price_per_night', 'is_active']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_date')
        end = cleaned.get('end_date')
        if start and end and end < start:
            self.add_error('end_date', 'Дата окончания сезона не может быть раньше даты начала.')
        return cleaned


class CleaningForm(forms.ModelForm):
    class Meta:
        model = Cleaning
        fields = ['room', 'scheduled_date', 'cleaning_type', 'assigned_staff', 'status', 'notes']
        widgets = {
            'scheduled_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }
