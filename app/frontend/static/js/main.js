// Текущие параметры фильтрации
let currentFilters = {
    platform: '',
    start_date: '',
    end_date: '',
    source_id: '',
    limit: 100,
    offset: 0
};

// Загрузка данных при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
    // Установка начальных дат
    const today = new Date();
    const weekAgo = new Date(today);
    weekAgo.setDate(today.getDate() - 7);
    
    // Форматируем даты в ISO формат
    document.getElementById('startDate').value = weekAgo.toISOString().split('T')[0];
    document.getElementById('endDate').value = today.toISOString().split('T')[0];
    
    loadData();
    setupEventListeners();
});

// Настройка обработчиков событий
function setupEventListeners() {
    // Обработка формы фильтров
    document.getElementById('filterForm').addEventListener('submit', (e) => {
        e.preventDefault();
        currentFilters.offset = 0; // Сброс пагинации при изменении фильтров
        loadData();
    });

    // Обработка кнопок пагинации
    document.getElementById('prevPage').addEventListener('click', () => {
        if (currentFilters.offset >= currentFilters.limit) {
            currentFilters.offset -= currentFilters.limit;
            loadData();
        }
    });

    document.getElementById('nextPage').addEventListener('click', () => {
        currentFilters.offset += currentFilters.limit;
        loadData();
    });
}

// Загрузка данных с сервера
async function loadData() {
    try {
        // Сбор параметров фильтрации
        const formData = new FormData(document.getElementById('filterForm'));
        currentFilters.platform = formData.get('platform') || '';
        
        // Преобразуем даты в ISO формат
        const startDate = formData.get('start_date');
        const endDate = formData.get('end_date');
        currentFilters.start_date = startDate ? new Date(startDate).toISOString() : '';
        currentFilters.end_date = endDate ? new Date(endDate + 'T23:59:59').toISOString() : '';
        
        currentFilters.source_id = formData.get('source_id') || '';

        console.log('Отправка запроса с параметрами:', currentFilters);

        // Формирование URL с параметрами
        const params = new URLSearchParams(currentFilters);
        const response = await fetch(`/api/dashboard_data?${params}`);
        const data = await response.json();

        console.log('Получены данные:', data);

        // Обновление таблицы
        updateTable(data.mentions);
        
        // Обновление списка источников
        updateSources(data.sources);
        
        // Обновление состояния кнопок пагинации
        updatePaginationButtons(data.mentions.length);
    } catch (error) {
        console.error('Ошибка при загрузке данных:', error);
        alert('Произошла ошибка при загрузке данных');
    }
}

// Обновление таблицы упоминаний
function updateTable(mentions) {
    console.log('Обновление таблицы с упоминаниями:', mentions);
    
    const tbody = document.getElementById('mentionsTable');
    tbody.innerHTML = '';

    if (mentions.length === 0) {
        console.log('Нет данных для отображения');
        const row = document.createElement('tr');
        row.innerHTML = '<td colspan="5" class="text-center">Нет данных для отображения</td>';
        tbody.appendChild(row);
        return;
    }

    mentions.forEach(mention => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${formatDate(mention.mention_datetime)}</td>
            <td>${formatPlatform(mention.platform)}</td>
            <td>${mention.source_id}</td>
            <td>${mention.mention_text}</td>
            <td><a href="${mention.mention_link}" target="_blank" class="link-orange">Открыть</a></td>
        `;
        tbody.appendChild(row);
    });
}

// Форматирование платформы
function formatPlatform(platform) {
    const platforms = {
        'rss': 'RSS',
        'vk': 'VK',
        'telegram': 'Telegram'
    };
    return platforms[platform] || platform;
}

// Обновление списка источников
function updateSources(sources) {
    const select = document.getElementById('source');
    const currentValue = select.value;
    
    // Сохраняем опцию "Все"
    select.innerHTML = '<option value="">Все источники</option>';
    
    // Добавляем источники
    sources.forEach(source => {
        const option = document.createElement('option');
        option.value = source.source_id;
        option.textContent = source.source_name;
        select.appendChild(option);
    });
    
    // Восстанавливаем выбранное значение
    select.value = currentValue;
}

// Обновление состояния кнопок пагинации
function updatePaginationButtons(mentionsCount) {
    const prevButton = document.getElementById('prevPage');
    const nextButton = document.getElementById('nextPage');
    
    prevButton.disabled = currentFilters.offset === 0;
    nextButton.disabled = mentionsCount < currentFilters.limit;
    
    // Добавляем/убираем класс disabled для стилизации
    if (prevButton.disabled) {
        prevButton.classList.add('disabled');
    } else {
        prevButton.classList.remove('disabled');
    }
    
    if (nextButton.disabled) {
        nextButton.classList.add('disabled');
    } else {
        nextButton.classList.remove('disabled');
    }
}

// Форматирование даты
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleString('ru-RU', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
} 