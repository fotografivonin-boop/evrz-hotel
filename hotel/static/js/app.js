document.addEventListener('DOMContentLoaded', function () {
    // 1. Сворачивание фильтров на планшете и телефоне (<= 768px)
    const filterButton = document.querySelector('.filter-toggle');
    const filterForm = document.querySelector('#catalog-filters');

    if (filterButton && filterForm) {
        if (window.matchMedia('(max-width: 768px)').matches) {
            filterForm.hidden = true;
            filterButton.setAttribute('aria-expanded', 'false');
        }
        filterButton.addEventListener('click', function () {
            filterForm.hidden = !filterForm.hidden;
            filterButton.setAttribute('aria-expanded', String(!filterForm.hidden));
        });
    }

    // 2. Мобильное меню-бургер
    const menuButton = document.querySelector('.menu-toggle');
    const navigation = document.querySelector('#navigation');

    if (menuButton && navigation) {
        menuButton.addEventListener('click', function () {
            const isOpen = menuButton.getAttribute('aria-expanded') === 'true';
            menuButton.setAttribute('aria-expanded', String(!isOpen));
            navigation.classList.toggle('open', !isOpen);
        });
    }

    // 3. Онлайн-расчёт стоимости проживания через fetch (/api/calc-price/)
    const priceBlock = document.querySelector('[data-calc-url]');

    if (priceBlock) {
        const checkIn = document.querySelector('#id_check_in_date');
        const checkOut = document.querySelector('#id_check_out_date');
        const result = document.querySelector('#quote-result');
        const tariffNote = document.querySelector('#quote-tariffs');
        const roomId = priceBlock.dataset.roomId;
        let currentController = null;

        async function calculatePrice() {
            if (!checkIn || !checkOut || !checkIn.value || !checkOut.value) {
                return;
            }

            if (currentController) {
                currentController.abort();
            }

            currentController = new AbortController();
            const timeoutId = setTimeout(function () {
                currentController.abort();
            }, 8000);

            result.className = 'price-result';
            result.textContent = 'Рассчитываем стоимость…';
            if (tariffNote) {
                tariffNote.textContent = '';
            }

            const params = new URLSearchParams({
                room: roomId,
                check_in_date: checkIn.value,
                check_out_date: checkOut.value,
            });

            try {
                const response = await fetch(priceBlock.dataset.calcUrl + '?' + params.toString(), {
                    signal: currentController.signal,
                    headers: { 'Accept': 'application/json' },
                });

                let data = {};
                try {
                    data = await response.json();
                } catch (_parseErr) {
                    data = { error: 'Некорректный ответ сервера.' };
                }

                if (!response.ok) {
                    result.className = 'price-result is-error';
                    result.textContent = data.error || 'Выберите корректные даты.';
                } else if (!data.available) {
                    result.className = 'price-result is-error';
                    result.textContent = 'На выбранные даты номер уже занят.';
                } else {
                    const totalFormatted = Number(data.total).toLocaleString('ru-RU');
                    result.className = 'price-result is-ok';
                    result.textContent =
                        'Свободен · ' + data.nights + ' ноч. · Итого: ' + totalFormatted + ' ₽';
                    if (tariffNote && Array.isArray(data.tariffs) && data.tariffs.length > 0) {
                        tariffNote.textContent = 'Применён сезонный тариф: ' + data.tariffs.join(', ');
                    } else if (tariffNote) {
                        tariffNote.textContent = 'Расчёт по базовому тарифу номера.';
                    }
                }
            } catch (error) {
                if (error.name !== 'AbortError') {
                    result.className = 'price-result is-error';
                    result.textContent = 'Ошибка соединения при расчёте цены. Попробуйте ещё раз.';
                }
            } finally {
                clearTimeout(timeoutId);
            }
        }

        if (checkIn && checkOut) {
            checkIn.addEventListener('change', calculatePrice);
            checkOut.addEventListener('change', calculatePrice);
            if (checkIn.value && checkOut.value) {
                calculatePrice();
            }
        }
    }

    // 4. Динамическое добавление дополнительных гостей в форме брони
    const addGuestBtn = document.querySelector('#add-guest-btn');
    const extraGuestsBox = document.querySelector('#extra-guests-container');
    const guestsCountInput = document.querySelector('#id_guests_count');

    if (addGuestBtn && extraGuestsBox) {
        const maxGuests = Number(addGuestBtn.dataset.maxGuests || 1);

        addGuestBtn.addEventListener('click', function () {
            const currentExtra = extraGuestsBox.querySelectorAll('.extra-guest-card').length;
            if (currentExtra + 1 >= maxGuests) {
                addGuestBtn.disabled = true;
                return;
            }
            const idx = currentExtra + 2;
            const card = document.createElement('div');
            card.className = 'extra-guest-card';
            card.innerHTML =
                '<div class="section-line"><strong>Гость №' + idx + '</strong>' +
                '<button type="button" class="small danger remove-guest-btn">Удалить</button></div>' +
                '<div class="form-pole"><label>ФИО гостя</label>' +
                '<input type="text" name="extra_guest_name" maxlength="150" required></div>' +
                '<div class="form-grid-2">' +
                '<div class="form-pole"><label>Дата рождения</label>' +
                '<input type="date" name="extra_guest_birth" required></div>' +
                '<div class="form-pole"><label>Документ (паспорт)</label>' +
                '<input type="text" name="extra_guest_doc" maxlength="30" required></div>' +
                '</div>' +
                '<div class="form-pole"><label>Телефон (необязательно)</label>' +
                '<input type="tel" name="extra_guest_phone" maxlength="20"></div>';

            extraGuestsBox.appendChild(card);
            if (guestsCountInput) {
                guestsCountInput.value = String(extraGuestsBox.querySelectorAll('.extra-guest-card').length + 1);
            }
            if (extraGuestsBox.querySelectorAll('.extra-guest-card').length + 1 >= maxGuests) {
                addGuestBtn.disabled = true;
            }

            card.querySelector('.remove-guest-btn').addEventListener('click', function () {
                card.remove();
                addGuestBtn.disabled = false;
                if (guestsCountInput) {
                    guestsCountInput.value = String(extraGuestsBox.querySelectorAll('.extra-guest-card').length + 1);
                }
            });
        });
    }

    // 5. Клиентская проверка телефона на формах
    const forms = document.querySelectorAll('.validated-form');
    forms.forEach(function (form) {
        form.addEventListener('submit', function (event) {
            const phone = form.querySelector('[name=phone]');
            if (phone && phone.value.trim()) {
                if (/^\+?[0-9 ()-]{10,20}$/.test(phone.value.trim())) {
                    phone.setCustomValidity('');
                } else {
                    phone.setCustomValidity('Введите корректный номер телефона (10–20 символов).');
                }
            }
            if (!form.reportValidity()) {
                event.preventDefault();
            }
        });
    });
});
