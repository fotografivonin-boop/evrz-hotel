import csv
import logging
from datetime import date, timedelta
from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    BookingEditForm,
    BookingForm,
    BookingGuestForm,
    CleaningForm,
    RegisterForm,
    ReviewForm,
    TariffForm,
)
from .models import (
    Amenity,
    Booking,
    BookingGuest,
    Cleaning,
    Payment,
    Review,
    Room,
    RoomType,
    Tariff,
)
from .services import (
    ACTIVE_BOOKING_STATUSES,
    HotelBookingError,
    calculate_stay_price,
    create_checkout_cleaning,
    is_room_available,
    send_booking_email,
)

logger = logging.getLogger('hotel')

LOGIN_MAX_ATTEMPTS = 5
LOGIN_BLOCK_SECONDS = 600  # 10 минут


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '127.0.0.1')


def reception_required(view_func):
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not (request.user.is_active and request.user.is_staff):
            logger.warning(
                'Forbidden (403) reception access user=%s url=%s',
                request.user.username,
                request.path,
            )
            raise PermissionDenied('Доступ разрешён только администратору стойки и управляющему.')
        return view_func(request, *args, **kwargs)

    return _wrapped


def manager_required(view_func):
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not (request.user.is_active and request.user.is_superuser):
            logger.warning(
                'Forbidden (403) manager access user=%s url=%s',
                request.user.username,
                request.path,
            )
            raise PermissionDenied('Доступ разрешён только управляющему гостиницей.')
        return view_func(request, *args, **kwargs)

    return _wrapped


class RateLimitedLoginView(LoginView):
    template_name = 'login.html'

    def _keys(self, request, username=''):
        ip = _client_ip(request)
        uname = (username or '').strip().lower()
        return (
            f'login_attempts:{ip}:{uname}',
            f'login_blocked:{ip}:{uname}',
        )

    def post(self, request, *args, **kwargs):
        username = request.POST.get('username', '')
        attempts_key, blocked_key = self._keys(request, username)

        if cache.get(blocked_key):
            logger.warning('Rate limit blocked login for user=%s ip=%s', username, _client_ip(request))
            form = self.get_form()
            form.add_error(
                None,
                'Слишком много неудачных попыток входа (5 из 5). Повторите попытку через 10 минут.',
            )
            return self.render_to_response(self.get_context_data(form=form), status=429)

        form = self.get_form()
        if form.is_valid():
            cache.delete(attempts_key)
            cache.delete(blocked_key)
            return self.form_valid(form)

        attempts = cache.get(attempts_key, 0) + 1
        cache.set(attempts_key, attempts, LOGIN_BLOCK_SECONDS)
        if attempts >= LOGIN_MAX_ATTEMPTS:
            cache.set(blocked_key, True, LOGIN_BLOCK_SECONDS)
            logger.warning(
                'Login rate limit triggered (%s attempts) user=%s ip=%s',
                attempts,
                username,
                _client_ip(request),
            )
            form.add_error(
                None,
                'Превышено число попыток входа (5). Вход временно заблокирован на 10 минут.',
            )
            return self.render_to_response(self.get_context_data(form=form), status=429)

        return self.form_invalid(form)


def build_pagination_context(request, page):
    """Сохраняет все GET-параметры фильтрации и сортировки при переходе по страницам."""
    if page.paginator.num_pages <= 1:
        return None
    params = request.GET.copy()
    params.pop('page', None)
    base_qs = params.urlencode()
    prefix = f'?{base_qs}&page=' if base_qs else '?page='
    pages = [
        {'num': num, 'url': f'{prefix}{num}', 'current': num == page.number}
        for num in page.paginator.page_range
    ]
    return {
        'previous_url': f'{prefix}{page.previous_page_number()}' if page.has_previous() else None,
        'next_url': f'{prefix}{page.next_page_number()}' if page.has_next() else None,
        'pages': pages,
    }


def _parse_filter_dates(request):
    raw_in = (request.GET.get('check_in') or request.GET.get('check_in_date') or '').strip()
    raw_out = (request.GET.get('check_out') or request.GET.get('check_out_date') or '').strip()
    if not raw_in and not raw_out:
        return None, None, None
    if not raw_in or not raw_out:
        return None, None, 'Укажите обе даты: заезда и выезда.'
    try:
        d_in = date.fromisoformat(raw_in)
        d_out = date.fromisoformat(raw_out)
    except ValueError:
        logger.warning('Invalid filter dates: in=%s out=%s', raw_in, raw_out)
        return None, None, 'Некорректный формат дат.'
    if d_out <= d_in:
        return None, None, 'Дата выезда должна быть позже даты заезда.'
    if (d_out - d_in).days > 30:
        return None, None, 'Максимальный срок бронирования — 30 ночей.'
    return d_in, d_out, None


def catalog(request):
    rooms = (
        Room.objects.filter(is_active=True)
        .select_related('room_type')
        .prefetch_related('amenities')
    )
    query = request.GET.get('q', '').strip()
    room_type = (request.GET.get('room_type') or request.GET.get('type') or '').strip()
    max_price = request.GET.get('max_price', '').strip()
    selected_amenities = [a for a in request.GET.getlist('amenities') if a.isdigit()]
    sort = request.GET.get('sort', '').strip()

    if query:
        rooms = rooms.filter(
            Q(room_number__icontains=query)
            | Q(room_type__name__icontains=query)
            | Q(description__icontains=query)
        )
    if room_type.isdigit():
        rooms = rooms.filter(room_type_id=int(room_type))
    if max_price.isdigit():
        rooms = rooms.filter(room_type__base_price__lte=int(max_price))
    for amenity_id in selected_amenities:
        rooms = rooms.filter(amenities__id=int(amenity_id))

    d_in, d_out, date_error = _parse_filter_dates(request)
    if d_in and d_out:
        busy_bookings = Booking.objects.filter(
            status__in=ACTIVE_BOOKING_STATUSES,
            check_in_date__lt=d_out,
            check_out_date__gt=d_in,
        )
        rooms = rooms.exclude(bookings__in=busy_bookings)

    sort_map = {
        'price': ('room_type__base_price', 'room_number'),
        '-price': ('-room_type__base_price', 'room_number'),
        'guests': ('room_type__max_guests', 'room_number'),
        '-guests': ('-room_type__max_guests', 'room_number'),
        'floor': ('floor', 'room_number'),
        '-floor': ('-floor', 'room_number'),
    }
    if sort in sort_map:
        rooms = rooms.order_by(*sort_map[sort])
    else:
        rooms = rooms.order_by('floor', 'room_number')

    rooms = rooms.distinct()
    paginator = Paginator(rooms, 20)
    page = paginator.get_page(request.GET.get('page'))

    today = date.today()
    active_tariffs = {
        t.room_type_id: t
        for t in Tariff.objects.filter(
            is_active=True,
            start_date__lte=today,
            end_date__gte=today,
        ).order_by('start_date')
    }
    for room in page.object_list:
        room.current_tariff = active_tariffs.get(room.room_type_id)

    title = 'Результаты поиска' if request.path.startswith('/search/') else 'Каталог номеров'
    check_in_val = (request.GET.get('check_in') or request.GET.get('check_in_date') or '').strip()
    check_out_val = (request.GET.get('check_out') or request.GET.get('check_out_date') or '').strip()

    context = {
        'page_obj': page,
        'types': RoomType.objects.all(),
        'amenities_list': Amenity.objects.all(),
        'selected_type': room_type,
        'selected_amenities': [int(x) for x in selected_amenities],
        'query': query,
        'max_price': max_price,
        'check_in_val': check_in_val,
        'check_out_val': check_out_val,
        'date_error': date_error,
        'sort': sort,
        'page_title': title,
        'pagination': build_pagination_context(request, page),
    }
    return TemplateResponse(request, 'catalog.html', context)


def room_detail(request, pk):
    room = get_object_or_404(
        Room.objects.select_related('room_type').prefetch_related(
            'amenities', 'reviews__user', 'room_type__tariffs'
        ),
        pk=pk,
        is_active=True,
    )
    active_tariffs = room.room_type.tariffs.filter(is_active=True).order_by('start_date')
    avg_rating = room.reviews.aggregate(avg=Avg('rating'))['avg']
    context = {
        'room': room,
        'active_tariffs': active_tariffs,
        'avg_rating': avg_rating,
    }
    return TemplateResponse(request, 'room_detail.html', context)


def _calc_price_response(request, pk=None):
    room_param = pk or request.GET.get('room_id') or request.GET.get('room')
    if not room_param:
        logger.warning('Missing room param in /api/calc-price/')
        return JsonResponse({'error': 'Не указан номер комнаты.'}, status=400)

    room_qs = Room.objects.select_related('room_type').filter(is_active=True)
    room = None
    if str(room_param).isdigit():
        room = room_qs.filter(pk=int(room_param)).first()
        if room is None:
            room = room_qs.filter(room_number=str(room_param)).first()
    else:
        room = room_qs.filter(room_number=str(room_param)).first()

    if room is None:
        logger.warning('Room not found in /api/calc-price/: room=%s', room_param)
        return JsonResponse({'error': 'Указанный номер не найден.'}, status=404)

    raw_in = (
        request.GET.get('check_in_date')
        or request.GET.get('check_in')
        or request.GET.get('in')
        or ''
    ).strip()
    raw_out = (
        request.GET.get('check_out_date')
        or request.GET.get('check_out')
        or request.GET.get('out')
        or ''
    ).strip()

    try:
        start = date.fromisoformat(raw_in)
        end = date.fromisoformat(raw_out)
    except ValueError:
        logger.warning('Bad date format in /api/calc-price/: in=%s out=%s', raw_in, raw_out)
        return JsonResponse({'error': 'Выберите корректные даты заезда и выезда.'}, status=400)

    if start < date.today():
        return JsonResponse({'error': 'Дата заезда не может быть в прошлом.'}, status=400)
    if end <= start:
        return JsonResponse({'error': 'Дата выезда должна быть позже даты заезда.'}, status=400)

    nights = (end - start).days
    if nights > 30:
        return JsonResponse({'error': 'Максимальный срок бронирования — 30 ночей.'}, status=400)

    try:
        total, tariffs = calculate_stay_price(room, start, end)
    except HotelBookingError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    return JsonResponse({
        'room_id': room.pk,
        'room_number': room.room_number,
        'available': is_room_available(room, start, end),
        'nights': nights,
        'total': str(total),
        'base_price': str(room.room_type.base_price),
        'tariffs': tariffs,
    })


def api_calc_price(request):
    return _calc_price_response(request)


def quote(request, pk):
    return _calc_price_response(request, pk=pk)


@login_required
def book(request, pk):
    room = get_object_or_404(Room.objects.select_related('room_type'), pk=pk, is_active=True)

    extra_names = [v.strip() for v in request.POST.getlist('extra_guest_name') if v.strip()]
    extra_births = request.POST.getlist('extra_guest_birth')
    extra_docs = request.POST.getlist('extra_guest_doc')
    extra_phones = request.POST.getlist('extra_guest_phone')

    initial = {}
    if request.method == 'GET':
        if request.GET.get('check_in') or request.GET.get('check_in_date'):
            initial['check_in_date'] = request.GET.get('check_in') or request.GET.get('check_in_date')
        if request.GET.get('check_out') or request.GET.get('check_out_date'):
            initial['check_out_date'] = request.GET.get('check_out') or request.GET.get('check_out_date')
        if request.user.email:
            initial['email'] = request.user.email
        full = request.user.get_full_name().strip()
        if full:
            initial['full_name'] = full

    form = BookingForm(
        request.POST or None,
        initial=initial,
        room=room,
        extra_guests_count=len(extra_names),
    )

    if request.method == 'POST' and form.is_valid():
        start = form.cleaned_data['check_in_date']
        end = form.cleaned_data['check_out_date']

        try:
            with transaction.atomic():
                Room.objects.select_for_update().get(pk=room.pk)
                if not is_room_available(room, start, end):
                    form.add_error(None, 'Выбранные даты уже заняты. Выберите другие дни.')
                else:
                    total, _tariffs = calculate_stay_price(room, start, end)
                    booking = Booking.objects.create(
                        user=request.user,
                        room=room,
                        check_in_date=start,
                        check_out_date=end,
                        nights_count=(end - start).days,
                        total_price=total,
                        status='new',
                        comment=form.cleaned_data['comment'],
                        contact_name=form.cleaned_data['full_name'],
                        contact_phone=form.cleaned_data['phone'],
                        contact_email=form.cleaned_data['email'],
                    )
                    BookingGuest.objects.create(
                        booking=booking,
                        full_name=form.cleaned_data['full_name'],
                        birth_date=form.cleaned_data['birth_date'],
                        document_number=form.cleaned_data['document_number'],
                        phone=form.cleaned_data['phone'],
                    )
                    for idx, name in enumerate(extra_names):
                        b_raw = extra_births[idx] if idx < len(extra_births) and extra_births[idx] else ''
                        try:
                            b_date = date.fromisoformat(b_raw) if b_raw else form.cleaned_data['birth_date']
                        except ValueError:
                            b_date = form.cleaned_data['birth_date']
                        doc = extra_docs[idx].strip() if idx < len(extra_docs) and extra_docs[idx].strip() else 'Не указан'
                        ph = extra_phones[idx].strip() if idx < len(extra_phones) else ''
                        BookingGuest.objects.create(
                            booking=booking,
                            full_name=name,
                            birth_date=b_date,
                            document_number=doc,
                            phone=ph,
                        )
                    Payment.objects.create(
                        booking=booking,
                        amount=booking.total_price,
                        payment_method=form.cleaned_data['payment_method'],
                        status='pending',
                        receipt_number=f'VOLGA-{booking.pk}-{timezone.now():%Y%m%d%H%M%S}',
                    )

                    send_booking_email(
                        subject=f'ОТЕЛЬ ВОЛГА: подтверждение бронирования №{booking.pk}',
                        message=(
                            f'Здравствуйте, {booking.contact_name}!\n'
                            f'Вы оформили бронь №{booking.pk} на номер {room.room_number} ({room.room_type.name}).\n'
                            f'Даты проживания: {start:%d.%m.%Y} — {end:%d.%m.%Y} ({booking.nights_count} ноч.).\n'
                            f'Итоговая стоимость: {booking.total_price} руб.\n'
                        ),
                        recipient_email=booking.contact_email or request.user.email,
                    )
                    messages.success(request, 'Бронирование успешно создано. Сохраните печатный ваучер.')
                    return redirect('voucher', pk=booking.pk)
        except (IntegrityError, DatabaseError) as exc:
            logger.error('Booking transaction rolled back for room=%s: %s', room.pk, exc)
            form.add_error(None, 'Ошибка сохранения бронирования. Попробуйте отправить форму ещё раз.')

    context = {
        'room': room,
        'form': form,
    }
    return TemplateResponse(request, 'book.html', context)


def _get_owned_booking_or_403(request, pk, allow_staff=True):
    booking = get_object_or_404(
        Booking.objects.select_related('room__room_type', 'user').prefetch_related('guests', 'payments'),
        pk=pk,
    )
    is_owner = booking.user_id == request.user.id
    if not is_owner and not (allow_staff and request.user.is_staff):
        logger.warning(
            'Forbidden (403) user=%s url=%s booking_owner=%s',
            request.user.username,
            request.path,
            booking.user_id,
        )
        raise PermissionDenied('У вас нет прав на просмотр или изменение чужого бронирования.')
    return booking


@login_required
def my_bookings(request):
    bookings = (
        Booking.objects.filter(user=request.user)
        .select_related('room__room_type')
        .prefetch_related('payments')
    )
    paginator = Paginator(bookings, 20)
    page = paginator.get_page(request.GET.get('page'))
    today = date.today()
    for booking in page:
        booking.can_cancel = booking.status in ('new', 'confirmed') and booking.check_in_date >= today
        booking.has_review = hasattr(booking, 'review')
        booking.can_review = booking.status == 'checked_out' and not booking.has_review
    context = {
        'page_obj': page,
        'pagination': build_pagination_context(request, page),
    }
    return TemplateResponse(request, 'my_bookings.html', context)


@login_required
def booking_detail(request, pk):
    booking = _get_owned_booking_or_403(request, pk, allow_staff=True)
    edit_form = BookingEditForm(instance=booking)
    guest_form = BookingGuestForm()

    if request.method == 'POST':
        action = request.POST.get('action', 'update_comment')
        if action == 'update_comment':
            edit_form = BookingEditForm(request.POST, instance=booking)
            if edit_form.is_valid():
                edit_form.save()
                messages.success(request, 'Комментарий к бронированию обновлён.')
                return redirect('booking_detail', pk=booking.pk)
        elif action == 'add_guest':
            guest_form = BookingGuestForm(request.POST)
            if booking.guests.count() >= booking.room.room_type.max_guests:
                messages.error(
                    request,
                    f'Достигнут лимит вместимости номера ({booking.room.room_type.max_guests} чел.).',
                )
            elif guest_form.is_valid():
                guest = guest_form.save(commit=False)
                guest.booking = booking
                guest.save()
                messages.success(request, 'Гость добавлен к бронированию.')
                return redirect('booking_detail', pk=booking.pk)

    can_cancel = booking.status in ('new', 'confirmed') and booking.check_in_date >= date.today()
    context = {
        'booking': booking,
        'edit_form': edit_form,
        'guest_form': guest_form,
        'can_cancel': can_cancel,
        'has_review': hasattr(booking, 'review'),
    }
    return TemplateResponse(request, 'booking_detail.html', context)


@login_required
def voucher(request, pk):
    booking = _get_owned_booking_or_403(request, pk, allow_staff=True)
    context = {'booking': booking}
    return TemplateResponse(request, 'voucher.html', context)


@login_required
def cancel(request, pk):
    booking = _get_owned_booking_or_403(request, pk, allow_staff=False)
    is_cancellable = booking.status in ('new', 'confirmed') and booking.check_in_date >= date.today()

    if not is_cancellable:
        messages.error(request, 'Эту бронь нельзя отменить (она уже заселена, завершена или отменена).')
        return redirect('my_bookings')

    if request.method == 'POST':
        with transaction.atomic():
            booking.status = 'cancelled'
            booking.save(update_fields=['status'])
            booking.payments.filter(status='paid').update(status='refunded')
        send_booking_email(
            subject=f'ОТЕЛЬ ВОЛГА: отмена бронирования №{booking.pk}',
            message=f'Ваша бронь №{booking.pk} на номер {booking.room.room_number} отменена.',
            recipient_email=booking.contact_email or request.user.email,
        )
        messages.success(request, f'Бронирование №{booking.pk} отменено.')
        return redirect('my_bookings')

    return TemplateResponse(request, 'cancel_confirm.html', {'booking': booking})


@login_required
def review_add(request, pk=None):
    eligible_bookings = Booking.objects.filter(
        user=request.user,
        status='checked_out',
        review__isnull=True,
    ).select_related('room__room_type')

    booking = None
    booking_id = pk or request.GET.get('booking') or request.POST.get('booking_id')
    if booking_id and str(booking_id).isdigit():
        booking = get_object_or_404(Booking, pk=int(booking_id))
        if booking.user_id != request.user.id:
            logger.warning('Forbidden (403) review add by user=%s on booking=%s', request.user.username, booking.pk)
            raise PermissionDenied('Нельзя оставить отзыв на чужое бронирование.')
        if booking.status != 'checked_out' or hasattr(booking, 'review'):
            messages.error(request, 'Отзыв доступен только после выезда и один раз по каждой брони.')
            return redirect('my_bookings')

    form = ReviewForm(request.POST or None, request.FILES or None)
    if request.method == 'POST':
        if booking is None:
            messages.error(request, 'Выберите завершённое бронирование для отзыва.')
        elif form.is_valid():
            rev = form.save(commit=False)
            rev.booking = booking
            rev.room = booking.room
            rev.user = request.user
            rev.save()
            messages.success(request, 'Спасибо! Ваш отзыв опубликован.')
            return redirect('room_detail', pk=booking.room_id)

    context = {
        'form': form,
        'title': 'Оставить отзыв',
        'booking': booking,
        'eligible_bookings': eligible_bookings,
    }
    return TemplateResponse(request, 'review_form.html', context)


@login_required
def review_edit(request, pk):
    rev = get_object_or_404(Review.objects.select_related('room'), pk=pk)
    if rev.user_id != request.user.id:
        raise PermissionDenied('Вы можете редактировать только собственные отзывы.')
    form = ReviewForm(request.POST or None, request.FILES or None, instance=rev)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Отзыв обновлён.')
        return redirect('room_detail', pk=rev.room_id)
    context = {'form': form, 'title': 'Редактировать отзыв', 'booking': rev.booking, 'is_edit': True}
    return TemplateResponse(request, 'review_form.html', context)


@login_required
@require_POST
def review_delete(request, pk):
    rev = get_object_or_404(Review, pk=pk)
    if rev.user_id != request.user.id and not request.user.is_superuser:
        raise PermissionDenied('Вы можете удалить только собственный отзыв.')
    room_id = rev.room_id
    rev.delete()
    messages.success(request, 'Отзыв удалён.')
    return redirect('room_detail', pk=room_id)


def register(request):
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            user = form.save()
            login(request, user)
            messages.success(request, 'Аккаунт успешно создан.')
            return redirect('room_list')
        except IntegrityError as exc:
            logger.warning('Duplicate registration attempt: %s', exc)
            form.add_error('username', 'Пользователь с таким логином уже существует.')

    context = {'form': form, 'title': 'Регистрация'}
    return TemplateResponse(request, 'form.html', context)


def about(request):
    return TemplateResponse(request, 'about.html')


@reception_required
def staff_bookings(request):
    qs = Booking.objects.select_related('room__room_type', 'user').prefetch_related('payments')
    q = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    if q:
        qs = qs.filter(
            Q(room__room_number__icontains=q)
            | Q(user__username__icontains=q)
            | Q(contact_name__icontains=q)
        )
    if status_filter:
        qs = qs.filter(status=status_filter)

    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get('page'))
    context = {
        'title': 'Панель стойки',
        'page_obj': page,
        'query': q,
        'status_filter': status_filter,
        'status_choices': Booking.STATUS_CHOICES,
        'pagination': build_pagination_context(request, page),
    }
    return TemplateResponse(request, 'staff.html', context)


@reception_required
def staff_checkin(request):
    if request.method == 'POST':
        booking_id = request.POST.get('booking_id')
        action = request.POST.get('action', 'checkin')
        booking = get_object_or_404(Booking.objects.select_related('room'), pk=booking_id)

        if action == 'mark_paid':
            with transaction.atomic():
                payment = booking.payments.first()
                if payment:
                    payment.status = 'paid'
                    payment.paid_at = timezone.now()
                    payment.save(update_fields=['status', 'paid_at'])
                else:
                    Payment.objects.create(
                        booking=booking,
                        amount=booking.total_price,
                        payment_method='pos_desk',
                        status='paid',
                        paid_at=timezone.now(),
                        receipt_number=f'DESK-{booking.pk}-{timezone.now():%Y%m%d%H%M%S}',
                    )
                if booking.status == 'new':
                    booking.status = 'confirmed'
                    booking.save(update_fields=['status'])
            messages.success(request, f'Оплата по брони №{booking.pk} отмечена.')
        elif action == 'checkin':
            pending_cleaning = Cleaning.objects.filter(
                room=booking.room,
                status__in=('scheduled', 'in_progress'),
            ).exists()
            if pending_cleaning and request.POST.get('force') != '1':
                messages.error(
                    request,
                    f'Номер {booking.room.room_number} ещё не прошёл уборку. Завершите уборку в графике.',
                )
            else:
                booking.status = 'checked_in'
                booking.save(update_fields=['status'])
                send_booking_email(
                    subject=f'ОТЕЛЬ ВОЛГА: заселение по брони №{booking.pk}',
                    message=f'Добро пожаловать! Статус вашей брони №{booking.pk} изменён на «Заселён».',
                    recipient_email=booking.contact_email or booking.user.email,
                )
                messages.success(request, f'Гость по брони №{booking.pk} заселён в номер {booking.room.room_number}.')
        return redirect(request.POST.get('next') or 'staff_checkin')

    arrivals = Booking.objects.filter(
        status__in=('new', 'confirmed')
    ).select_related('room__room_type', 'user').prefetch_related('payments').order_by('check_in_date')
    return TemplateResponse(request, 'staff_checkin.html', {'arrivals': arrivals})


@reception_required
def staff_checkout(request, pk):
    booking = get_object_or_404(Booking.objects.select_related('room', 'user'), pk=pk)
    if request.method == 'POST':
        if booking.status != 'checked_out':
            with transaction.atomic():
                booking.status = 'checked_out'
                booking.save(update_fields=['status'])
                create_checkout_cleaning(booking)
            send_booking_email(
                subject=f'ОТЕЛЬ ВОЛГА: завершение проживания №{booking.pk}',
                message=(
                    f'Спасибо, что выбрали «ОТЕЛЬ ВОЛГА»! '
                    f'Теперь вы можете оставить отзыв о номере {booking.room.room_number} в личном кабинете.'
                ),
                recipient_email=booking.contact_email or booking.user.email,
            )
            messages.success(
                request,
                f'Выезд по брони №{booking.pk} оформлен. Задача на уборку номера {booking.room.room_number} создана автоматически.',
            )
        return redirect('staff_bookings')
    return redirect('staff_bookings')


@reception_required
def cleaning(request):
    form = CleaningForm(request.POST or None)
    if request.method == 'POST':
        action = request.POST.get('action', 'create')
        if action == 'update_status':
            item = get_object_or_404(Cleaning, pk=request.POST.get('cleaning_id'))
            new_status = request.POST.get('status')
            if new_status in dict(Cleaning.STATUS_CHOICES):
                item.status = new_status
                item.save(update_fields=['status'])
                messages.success(request, f'Статус уборки номера {item.room.room_number} обновлён.')
            return redirect('cleaning')
        elif form.is_valid():
            form.save()
            messages.success(request, 'Задача на уборку добавлена.')
            return redirect('cleaning')

    cleanings = Cleaning.objects.select_related('room')
    paginator = Paginator(cleanings, 20)
    page = paginator.get_page(request.GET.get('page'))
    context = {
        'page_obj': page,
        'form': form,
        'status_choices': Cleaning.STATUS_CHOICES,
        'pagination': build_pagination_context(request, page),
    }
    return TemplateResponse(request, 'cleaning.html', context)


def _filter_month_queryset(qs, month_str, date_field='check_in_date'):
    if not month_str:
        return qs
    try:
        year_s, mon_s = month_str.split('-')
        return qs.filter(**{f'{date_field}__year': int(year_s), f'{date_field}__month': int(mon_s)})
    except (ValueError, TypeError):
        return qs


@manager_required
def stats(request):
    month_str = request.GET.get('month', '').strip()
    bookings_qs = _filter_month_queryset(Booking.objects.all(), month_str, 'check_in_date')
    payments_qs = Payment.objects.filter(status='paid', booking__in=bookings_qs)

    agg_bookings = bookings_qs.aggregate(
        total_count=Count('id'),
        avg_check=Coalesce(Avg('total_price'), Decimal('0.00')),
    )
    revenue = payments_qs.aggregate(
        total=Coalesce(Sum('amount'), Decimal('0.00'))
    )['total']
    avg_rating = Review.objects.aggregate(avg=Avg('rating'))['avg'] or 0

    total_rooms = Room.objects.filter(is_active=True).count()
    active_count = bookings_qs.filter(status__in=ACTIVE_BOOKING_STATUSES).count()
    occupancy_pct = round((active_count / total_rooms) * 100, 1) if total_rooms > 0 else 0.0

    # Данные для столбчатого SVG-графика выручки по категориям номеров
    chart_raw = (
        bookings_qs.exclude(status='cancelled')
        .values('room__room_type__name')
        .annotate(total=Coalesce(Sum('total_price'), Decimal('0.00')))
        .order_by('-total')[:6]
    )
    max_val = max((float(row['total']) for row in chart_raw), default=1.0) or 1.0
    chart_bars = []
    for idx, row in enumerate(chart_raw):
        val = float(row['total'])
        pct = round((val / max_val) * 100, 1) if max_val > 0 else 0
        bar_h = max(8, round((val / max_val) * 160))
        chart_bars.append({
            'label': row['room__room_type__name'][:18],
            'full_label': row['room__room_type__name'],
            'value': int(round(val)),
            'pct': pct,
            'x': 28 + idx * 105,
            'y': 180 - bar_h,
            'height': bar_h,
        })

    context = {
        'month': month_str,
        'room_count': total_rooms,
        'booking_count': agg_bookings['total_count'],
        'active_count': active_count,
        'revenue': revenue,
        'avg_check': agg_bookings['avg_check'],
        'avg_rating': round(float(avg_rating), 2),
        'occupancy_pct': occupancy_pct,
        'chart_bars': chart_bars,
    }
    return TemplateResponse(request, 'stats.html', context)


@manager_required
def manager_tariffs(request):
    form = TariffForm(request.POST or None)
    if request.method == 'POST':
        action = request.POST.get('action', 'create')
        if action == 'delete':
            t = get_object_or_404(Tariff, pk=request.POST.get('tariff_id'))
            t.delete()
            messages.success(request, 'Тариф удалён.')
            return redirect('manager_tariffs')
        elif action == 'toggle':
            t = get_object_or_404(Tariff, pk=request.POST.get('tariff_id'))
            t.is_active = not t.is_active
            t.save(update_fields=['is_active'])
            messages.success(request, f'Статус тарифа «{t.name}» изменён.')
            return redirect('manager_tariffs')
        elif form.is_valid():
            form.save()
            messages.success(request, 'Сезонный тариф сохранён.')
            return redirect('manager_tariffs')

    tariffs = Tariff.objects.select_related('room_type').all()
    return TemplateResponse(request, 'manager_tariffs.html', {'tariffs': tariffs, 'form': form})


@manager_required
def export_csv(request):
    month_str = request.GET.get('month', '').strip()
    bookings = _filter_month_queryset(
        Booking.objects.select_related('room__room_type', 'user').order_by('-created_at'),
        month_str,
        'check_in_date',
    )

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    filename = f'hotel_volga_report_{month_str or "all"}.csv'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write('\ufeff')  # UTF-8 BOM для корректного открытия в Excel

    writer = csv.writer(response, delimiter=';')
    writer.writerow([
        'ID брони',
        'Номер',
        'Категория',
        'Клиент',
        'Дата заезда',
        'Дата выезда',
        'Ночей',
        'Статус',
        'Сумма (руб.)',
    ])

    total_sum = Decimal('0.00')
    count = 0
    for b in bookings:
        writer.writerow([
            b.pk,
            b.room.room_number,
            b.room.room_type.name,
            b.user.username,
            b.check_in_date.strftime('%d.%m.%Y'),
            b.check_out_date.strftime('%d.%m.%Y'),
            b.nights_count,
            b.get_status_display(),
            f'{b.total_price:.2f}',
        ])
        total_sum += b.total_price
        count += 1

    avg_check = (total_sum / count) if count > 0 else Decimal('0.00')
    if count > 0:
        writer.writerow([])
        writer.writerow(['ИТОГО', f'Броней: {count}', '', '', '', '', '', f'Средний чек: {avg_check:.2f}', f'{total_sum:.2f}'])
    else:
        logger.info('Empty stats period requested for CSV export: month=%s', month_str or 'all')

    return response
