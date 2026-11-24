document.addEventListener('DOMContentLoaded', function () {
    const filterButton = document.querySelector('.filter-toggle');
    const filterForm = document.querySelector('#catalog-filters');
    const menuButton = document.querySelector('.menu-toggle');
    const navigation = document.querySelector('#navigation');
    const priceBlock = document.querySelector('[data-quote-url]');

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

    if (menuButton) {
        menuButton.addEventListener('click', function () {
            const isOpen = menuButton.getAttribute('aria-expanded') === 'true';
            menuButton.setAttribute('aria-expanded', String(!isOpen));
            navigation.classList.toggle('open', !isOpen);
        });
    }

    if (priceBlock) {
        const checkIn = document.querySelector('#id_check_in_date');
        const checkOut = document.querySelector('#id_check_out_date');
        const result = document.querySelector('#quote-result');
        let currentRequest;

        async function calculatePrice() {
            if (!checkIn.value || !checkOut.value) {
                return;
            }

            if (currentRequest) {
                currentRequest.abort();
            }

            currentRequest = new AbortController();
            result.textContent = 'Рассчитываем стоимость…';

            const dates = new URLSearchParams({
                check_in_date: checkIn.value,
                check_out_date: checkOut.value
            });

            try {
                const response = await fetch(priceBlock.dataset.quoteUrl + '?' + dates, {
                    signal: currentRequest.signal
                });
                const data = await response.json();

                if (!response.ok) {
                    result.textContent = data.error;
                } else if (!data.available) {
                    result.textContent = 'На эти даты номер занят.';
                } else {
                    const total = Number(data.total).toLocaleString('ru-RU');
                    result.textContent = 'Свободен · ' + data.nights + ' ноч. · Итого ' + total + ' ₽';
                }
            } catch (error) {
                if (error.name !== 'AbortError') {
                    result.textContent = 'Не удалось рассчитать стоимость. Попробуйте ещё раз.';
                }
            }
        }

        checkIn.addEventListener('change', calculatePrice);
        checkOut.addEventListener('change', calculatePrice);
        calculatePrice();
    }

    const forms = document.querySelectorAll('.validated-form');

    forms.forEach(function (form) {
        form.addEventListener('submit', function (event) {
            const phone = form.querySelector('[name=phone]');

            if (phone) {
                if (/^\+?[0-9 ()-]{10,20}$/.test(phone.value)) {
                    phone.setCustomValidity('');
                } else {
                    phone.setCustomValidity('Введите корректный номер телефона.');
                }
            }

            if (!form.reportValidity()) {
                event.preventDefault();
            }
        });
    });
});
