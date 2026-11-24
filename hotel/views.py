from datetime import date, timedelta
from decimal import Decimal
from django.contrib import messages
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.views.decorators.http import require_POST
from .models import Room, RoomType, Tariff, Booking, BookingGuest, Payment, Cleaning, Review


class BookingForm(forms.ModelForm):
    full_name = forms.CharField(label='ФИО гостя', max_length=150)
    phone = forms.RegexField(
        r'^\+?[0-9 ()-]{10,20}$',
        label='Телефон',
        error_messages={'invalid': 'Введите телефон из 10–20 символов.'},
    )
    email = forms.EmailField(label='Электронная почта')
    birth_date = forms.DateField(
        label='Дата рождения', widget=forms.DateInput(attrs={'type': 'date'})
    )
    document_number = forms.CharField(label='Документ гостя', max_length=30)
    payment_method = forms.ChoiceField(
        label='Способ оплаты',
        choices=[
            ('card_online', 'Карта на сайте'),
            ('cash_desk', 'Наличными на стойке'),
            ('pos_desk', 'Терминал на стойке'),
        ],
    )

    class Meta:
        model = Booking
        fields = ['check_in_date', 'check_out_date', 'comment']
        labels = {'check_in_date': 'Заезд', 'check_out_date': 'Выезд', 'comment': 'Пожелания'}
        widgets = {
            'check_in_date': forms.DateInput(attrs={'type': 'date'}),
            'check_out_date': forms.DateInput(attrs={'type': 'date'}),
            'comment': forms.Textarea(attrs={'rows': 3, 'maxlength': 500}),
        }

    def clean(self):
        data = super().clean()
        start, end = data.get('check_in_date'), data.get('check_out_date')
        if data.get('birth_date') and data['birth_date'] > date.today():
            self.add_error('birth_date', 'Дата рождения не может быть в будущем.')
        if start and start < date.today():
            self.add_error('check_in_date', 'Дата заезда уже прошла.')
        if start and end and end <= start:
            self.add_error('check_out_date', 'Выезд должен быть позже заезда.')
        if start and end and (end - start).days > 366:
            self.add_error('check_out_date', 'Бронирование возможно максимум на 366 ночей.')
        if len(data.get('comment', '')) > 500:
            self.add_error('comment', 'Не более 500 символов.')
        return data


class RegisterForm(UserCreationForm):
    email = forms.EmailField(label='Электронная почта')

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ['rating', 'text']
        widgets = {'text': forms.Textarea(attrs={'rows': 5, 'maxlength': 2000})}



def page_navigation(request, page):
    if page.paginator.num_pages <= 1:
        return []

    previous = []
    following = []
    params = request.GET.copy()
    if page.has_previous():
        params['page'] = page.previous_page_number()
        previous.append('?' + params.urlencode())
    if page.has_next():
        params['page'] = page.next_page_number()
        following.append('?' + params.urlencode())
    return [{'previous': previous, 'next': following}]


def available(room, start, end):
    bookings = Booking.objects.filter(
        room=room,
        check_in_date__lt=end,
        check_out_date__gt=start,
    )
    bookings = bookings.exclude(status__in=['cancelled', 'checked_out'])
    return not bookings.exists()


def price(room, start, end):
    total = Decimal('0')
    day = start

    while day < end:
        tariffs = Tariff.objects.filter(
            room_type=room.room_type,
            is_active=True,
            start_date__lte=day,
            end_date__gte=day,
        )
        tariff = tariffs.order_by('-start_date', '-pk').first()

        if tariff:
            total += tariff.price_per_night
        else:
            total += room.room_type.base_price
        day += timedelta(days=1)

    return total


def dates(request):
    try:
        start = date.fromisoformat(request.GET.get('check_in_date', ''))
        end = date.fromisoformat(request.GET.get('check_out_date', ''))
        if start < date.today() or end <= start or (end - start).days > 366:
            return None
        return start, end
    except ValueError:
        return None


def catalog(request):
    rooms = Room.objects.filter(is_active=True)
    rooms = rooms.select_related('room_type').prefetch_related('amenities')
    query = request.GET.get('q', '').strip()
    room_type = request.GET.get('type', '')
    max_price = request.GET.get('max_price', '')

    if query:
        rooms = rooms.filter(
            Q(room_number__icontains=query)
            | Q(room_type__name__icontains=query)
            | Q(description__icontains=query)
        )
    if room_type.isdigit():
        rooms = rooms.filter(room_type_id=room_type)
    if max_price.isdigit():
        rooms = rooms.filter(room_type__base_price__lte=int(max_price))

    stay = dates(request)
    if stay:
        bookings = Booking.objects.filter(
            check_in_date__lt=stay[1],
            check_out_date__gt=stay[0],
        )
        bookings = bookings.exclude(status__in=['cancelled', 'checked_out'])
        rooms = rooms.exclude(bookings__in=bookings)

    if request.GET.get('sort') == 'price':
        rooms = rooms.order_by('room_type__base_price', 'pk')

    paginator = Paginator(rooms.distinct(), 20)
    page = paginator.get_page(request.GET.get('page'))
    types = RoomType.objects.all()
    for category in types:
        category.selected = ''
        if str(category.pk) == room_type:
            category.selected = 'selected'
    sort_selected = ''
    if request.GET.get('sort') == 'price':
        sort_selected = 'selected'
    title = 'Каталог номеров'
    if request.path.startswith('/search/'):
        title = 'Результаты поиска'
    empty_rooms = []
    if not page.object_list:
        empty_rooms.append(True)
    context = {
        'page_obj': page,
        'types': types,
        'query': query,
        'page_title': title,
        'sort_selected': sort_selected,
        'empty_rooms': empty_rooms,
        'page_navigation': page_navigation(request, page),
    }
    return TemplateResponse(request, 'catalog.html', context)


def room_detail(request, pk):
    rooms = Room.objects.select_related('room_type')
    rooms = rooms.prefetch_related('amenities', 'reviews__user')
    room = get_object_or_404(rooms, pk=pk, is_active=True)
    no_amenities = []
    no_reviews = []
    if not room.amenities.all():
        no_amenities.append(True)
    if not room.reviews.all():
        no_reviews.append(True)
    context = {'room': room, 'no_amenities': no_amenities, 'no_reviews': no_reviews}
    return TemplateResponse(request, 'room_detail.html', context)


def quote(request, pk):
    room = get_object_or_404(Room.objects.select_related('room_type'), pk=pk, is_active=True)
    stay = dates(request)
    if not stay:
        return JsonResponse({'error': 'Выберите корректные даты (не более 366 ночей).'}, status=400)

    start, end = stay
    result = {
        'available': available(room, start, end),
        'nights': (end - start).days,
        'total': str(price(room, start, end)),
    }
    return JsonResponse(result)


@login_required
def book(request, pk):
    room = get_object_or_404(Room.objects.select_related('room_type'), pk=pk, is_active=True)
    form = BookingForm(request.POST or None, initial=request.GET)

    if request.method == 'POST' and form.is_valid():
        start = form.cleaned_data['check_in_date']
        end = form.cleaned_data['check_out_date']

        with transaction.atomic():
            Room.objects.select_for_update().get(pk=room.pk)

            if not available(room, start, end):
                form.add_error(None, 'На эти даты номер уже занят. Выберите другие даты.')
            else:
                booking = Booking()
                booking.user = request.user
                booking.room = room
                booking.check_in_date = start
                booking.check_out_date = end
                booking.comment = form.cleaned_data['comment']
                booking.nights_count = (end - start).days
                booking.total_price = price(room, start, end)
                booking.contact_name = form.cleaned_data['full_name']
                booking.contact_phone = form.cleaned_data['phone']
                booking.contact_email = form.cleaned_data['email']
                booking.save()

                guest = BookingGuest()
                guest.booking = booking
                guest.full_name = form.cleaned_data['full_name']
                guest.birth_date = form.cleaned_data['birth_date']
                guest.document_number = form.cleaned_data['document_number']
                guest.phone = form.cleaned_data['phone']
                guest.save()

                payment = Payment()
                payment.booking = booking
                payment.amount = booking.total_price
                payment.payment_method = form.cleaned_data['payment_method']
                payment.receipt_number = f'BOOK-{booking.pk}'
                payment.save()

                messages.success(request, 'Бронирование создано. Сохраните ваучер.')
                return redirect('voucher', pk=booking.pk)

    context = {'room': room, 'form': form}
    return TemplateResponse(request, 'book.html', context)


def owned_booking(request, pk):
    booking = get_object_or_404(Booking.objects.select_related('room__room_type', 'user'), pk=pk)
    if booking.user_id != request.user.id and not request.user.is_staff:
        return None
    return booking


@login_required
def my_bookings(request):
    bookings = Booking.objects.filter(user=request.user).select_related('room__room_type')
    paginator = Paginator(bookings, 20)
    page = paginator.get_page(request.GET.get('page'))
    for booking in page:
        booking.cancel_actions = []
        booking.review_actions = []
        if booking.status in ['new', 'confirmed']:
            booking.cancel_actions.append(booking.pk)
        if booking.status == 'checked_out':
            booking.review_actions.append(booking.pk)
    no_bookings = []
    if not page.object_list:
        no_bookings.append(True)
    context = {
        'page_obj': page,
        'no_bookings': no_bookings,
        'page_navigation': page_navigation(request, page),
    }
    return TemplateResponse(request, 'my_bookings.html', context)


@login_required
def voucher(request, pk):
    booking = owned_booking(request, pk)
    if booking is None:
        return HttpResponseForbidden('Доступ запрещён')
    context = {'booking': booking}
    return TemplateResponse(request, 'voucher.html', context)


@login_required
@require_POST
def cancel(request, pk):
    booking = get_object_or_404(Booking, pk=pk)
    if booking.user_id != request.user.id:
        return HttpResponseForbidden('Доступ запрещён')

    if booking.status in ['new', 'confirmed'] and booking.check_in_date > date.today():
        booking.status = 'cancelled'
        booking.save(update_fields=['status'])
        messages.success(request, 'Бронирование отменено.')
    else:
        messages.error(request, 'Эту бронь нельзя отменить.')
    return redirect('my_bookings')


@login_required
def review(request, pk):
    booking = get_object_or_404(Booking, pk=pk)
    if booking.user_id != request.user.id:
        return HttpResponseForbidden('Доступ запрещён')
    if booking.status != 'checked_out' or hasattr(booking, 'review'):
        return HttpResponseForbidden('Отзыв доступен после выезда и только один раз.')

    form = ReviewForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        review = Review()
        review.booking = booking
        review.room = booking.room
        review.user = request.user
        review.rating = form.cleaned_data['rating']
        review.text = form.cleaned_data['text']
        review.save()
        messages.success(request, 'Спасибо за отзыв!')
        return redirect('room_detail', pk=booking.room_id)

    context = {'form': form, 'title': 'Оставить отзыв'}
    return TemplateResponse(request, 'form.html', context)


def register(request):
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, 'Аккаунт создан.')
        return redirect('my_bookings')

    context = {'form': form, 'title': 'Регистрация'}
    return TemplateResponse(request, 'form.html', context)


def about(request):
    return TemplateResponse(request, 'about.html')


def is_staff(user):
    return user.is_active and user.is_staff


staff_required = user_passes_test(is_staff)


@staff_required
def staff_bookings(request):
    bookings = Booking.objects.select_related('room', 'user')
    paginator = Paginator(bookings, 20)
    page = paginator.get_page(request.GET.get('page'))
    no_bookings = []
    if not page.object_list:
        no_bookings.append(True)
    context = {
        'title': 'Панель стойки',
        'page_obj': page,
        'no_bookings': no_bookings,
        'page_navigation': page_navigation(request, page),
    }
    return TemplateResponse(request, 'staff.html', context)


@staff_required
def cleaning(request):
    cleanings = Cleaning.objects.select_related('room')
    paginator = Paginator(cleanings, 20)
    page = paginator.get_page(request.GET.get('page'))
    no_cleanings = []
    if not page.object_list:
        no_cleanings.append(True)
    context = {
        'page_obj': page,
        'no_cleanings': no_cleanings,
        'page_navigation': page_navigation(request, page),
    }
    return TemplateResponse(request, 'cleaning.html', context)


@staff_required
def stats(request):
    paid = Payment.objects.filter(status='paid').aggregate(total=Sum('amount'))
    active = Booking.objects.filter(status__in=['new', 'confirmed', 'checked_in'])
    context = {
        'room_count': Room.objects.count(),
        'booking_count': Booking.objects.count(),
        'revenue': paid['total'] or 0,
        'active_count': active.count(),
    }
    return TemplateResponse(request, 'stats.html', context)
