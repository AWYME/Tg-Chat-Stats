import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime
import heapq
import string

# Стоп-слова (можно расширить)
STOP_WORDS = {
    'и', 'в', 'во', 'на', 'с', 'со', 'а', 'но', 'за', 'по', 'у', 'к', 'из', 'о', 'об',
    'это', 'что', 'как', 'так', 'все', 'всё', 'было', 'нет', 'да', 'или', 'же', 'вот', 'бы',
    'i', 'you', 'he', 'she', 'it', 'we', 'they', 'to', 'for', 'of', 'on', 'with',
    'and', 'or', 'but', 'so', 'if', 'then', 'is', 'are', 'was', 'were', 'be', 'been'
}

# Регулярка для поиска эмодзи (базовый диапазон)
EMOJI_PATTERN = re.compile(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002702-\U000027B0\U000024C2-\U0001F251]+', re.UNICODE)

def clean_text(text: str) -> list:
    """Возвращает список слов, очищенных от знаков препинания и стоп-слов."""
    if not isinstance(text, str):
        return []
    text = re.sub(r'[^\w\sа-яё]', ' ', text.lower())
    words = text.split()
    return [w for w in words if w not in STOP_WORDS and len(w) > 1]

def detect_intonation(text: str) -> str:
    """Определяет интонацию по последним знакам препинания."""
    if not isinstance(text, str) or not text:
        return 'нейтральная'
    text = text.strip()
    if not text:
        return 'нейтральная'
    last_char = text[-1]
    # Проверка на многоточие в конце
    if text.endswith('...') or text.endswith('…'):
        return 'многоточие'
    if last_char == '!':
        return 'восклицание'
    if last_char == '?':
        return 'вопрос'
    if last_char == '.':
        return 'спокойная'
    return 'нейтральная'

def has_emoji(text: str) -> bool:
    return bool(EMOJI_PATTERN.search(text))

def analyze_telegram_json(input_path: str, output_md_path: str = None, min_messages_per_user: int = 10):
    if output_md_path is None:
        input_file = Path(input_path)
        output_md_path = input_file.parent / f"{input_file.stem}_advanced_stats.md"

    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    messages = data.get('messages', [])
    if not messages and isinstance(data, list):
        messages = data

    total = len(messages)

    # Общие счётчики
    overall_word_counter = Counter()
    overall_hourly = Counter()
    overall_media = Counter()
    overall_intonation = Counter()

    # Данные по пользователям
    user_data = defaultdict(lambda: {
        'msg_count': 0,
        'char_sum': 0,
        'word_counter': Counter(),
        'hourly': Counter(),
        'intonation': Counter(),
        'longest_messages': [],  # будет хранить (длина, текст, дата) топ-10
        'emoji_count': 0,
        'unique_words': set()
    })

    for msg in messages:
        author = msg.get('from') or msg.get('sender', 'Unknown')
        if not author and 'chat' in msg:
            author = msg['chat'].get('first_name', 'Unknown')
        if not author:
            author = 'Unknown'

        text = msg.get('text', '')
        if isinstance(text, list):
            text_parts = []
            for part in text:
                if isinstance(part, dict) and 'text' in part:
                    text_parts.append(part['text'])
                elif isinstance(part, str):
                    text_parts.append(part)
            text = ' '.join(text_parts)
        if not isinstance(text, str):
            text = ''

        # Общая статистика
        if text:
            words = clean_text(text)
            overall_word_counter.update(words)
        date_ts = msg.get('date_unixtime') or msg.get('timestamp')
        hour = None
        if date_ts:
            dt = datetime.fromtimestamp(int(date_ts))
            hour = dt.hour
            overall_hourly[hour] += 1

        media = msg.get('media_type')
        if media:
            overall_media[media] += 1

        # Интонация (для сообщений с текстом)
        if text:
            intonation = detect_intonation(text)
            overall_intonation[intonation] += 1

        # Теперь для пользователя
        ud = user_data[author]
        ud['msg_count'] += 1
        if text:
            ud['char_sum'] += len(text)
            words = clean_text(text)
            ud['word_counter'].update(words)
            ud['unique_words'].update(words)
            inton = detect_intonation(text)
            ud['intonation'][inton] += 1
            if has_emoji(text):
                ud['emoji_count'] += 1

            # Топ-10 самых длинных сообщений (храним только 10 лучших)
            msg_len = len(text)
            # Кортеж: (-длина, дата, текст) для heapq (храним отрицательную длину для min-heap)
            if len(ud['longest_messages']) < 10:
                heapq.heappush(ud['longest_messages'], (msg_len, date_ts or 0, text[:200]))  # обрезаем для читаемости
            else:
                # если текущая длина больше минимальной в куче
                if msg_len > ud['longest_messages'][0][0]:
                    heapq.heapreplace(ud['longest_messages'], (msg_len, date_ts or 0, text[:200]))

        if hour is not None:
            ud['hourly'][hour] += 1

    # Отфильтруем пользователей с минимальным количеством сообщений
    active_users = {name: data for name, data in user_data.items() if data['msg_count'] >= min_messages_per_user}
    # Сортируем по убыванию сообщений
    sorted_users = sorted(active_users.items(), key=lambda x: x[1]['msg_count'], reverse=True)

    # Генерация Markdown
    md_lines = []
    md_lines.append("# Расширенная статистика чата\n")
    md_lines.append(f"**Всего сообщений:** {total}\n")
    md_lines.append(f"**Участников с ≥{min_messages_per_user} сообщений:** {len(sorted_users)}\n")

    # Общая статистика по всем
    md_lines.append("## Общая статистика по чату\n")
    md_lines.append("### Топ-20 слов\n| Слово | Частота |\n|-------|---------|\n")
    for word, cnt in overall_word_counter.most_common(20):
        md_lines.append(f"| {word} | {cnt} |\n")

    md_lines.append("\n### Активность по часам (UTC)\n| Час | Сообщений | Диаграмма |\n|-----|-----------|----------|\n")
    max_hour = max(overall_hourly.values()) if overall_hourly else 1
    for hour in range(24):
        cnt = overall_hourly.get(hour, 0)
        bar = "█" * int(30 * cnt / max_hour)
        md_lines.append(f"| {hour:02d}:00 | {cnt} | {bar} |\n")

    if overall_media:
        md_lines.append("\n### Медиа-статистика\n| Тип | Количество |\n|-----|------------|\n")
        for media, cnt in overall_media.most_common():
            md_lines.append(f"| {media} | {cnt} |\n")

    md_lines.append("\n### Общая интонация сообщений\n| Интонация | Процент |\n|-----------|---------|\n")
    total_intoned = sum(overall_intonation.values())
    if total_intoned > 0:
        for inton, cnt in overall_intonation.most_common():
            percent = cnt / total_intoned * 100
            md_lines.append(f"| {inton} | {percent:.1f}% |\n")

    # Персональные блоки
    md_lines.append("\n---\n# Персональная статистика участников\n")
    for author, ud in sorted_users:
        msg_cnt = ud['msg_count']
        avg_len = ud['char_sum'] // msg_cnt if msg_cnt else 0
        unique_word_count = len(ud['unique_words'])
        total_words = sum(ud['word_counter'].values())
        lex_diversity = (unique_word_count / total_words * 100) if total_words else 0
        emoji_percent = (ud['emoji_count'] / msg_cnt * 100) if msg_cnt else 0

        md_lines.append(f"## {author}\n")
        md_lines.append(f"- **Сообщений:** {msg_cnt}\n")
        md_lines.append(f"- **Средняя длина:** {avg_len} симв.\n")
        md_lines.append(f"- **Уникальных слов:** {unique_word_count} (лексическое разнообразие {lex_diversity:.1f}%)\n")
        md_lines.append(f"- **Сообщений с эмодзи:** {ud['emoji_count']} ({emoji_percent:.1f}%)\n\n")

        # Часы активности участника
        md_lines.append("### Активность по часам\n| Час | Сообщений | Диаграмма |\n|-----|-----------|----------|\n")
        user_max_hour = max(ud['hourly'].values()) if ud['hourly'] else 1
        for hour in range(24):
            cnt = ud['hourly'].get(hour, 0)
            bar = "█" * int(20 * cnt / user_max_hour) if user_max_hour else ""
            md_lines.append(f"| {hour:02d}:00 | {cnt} | {bar} |\n")

        # Интонация участника
        md_lines.append("\n### Интонация сообщений\n| Интонация | Количество | Процент |\n|-----------|------------|---------|\n")
        user_inton_total = sum(ud['intonation'].values())
        for inton, cnt in ud['intonation'].most_common():
            percent = cnt / user_inton_total * 100 if user_inton_total else 0
            md_lines.append(f"| {inton} | {cnt} | {percent:.1f}% |\n")

        # Топ-10 слов участника
        md_lines.append("\n### Топ-10 слов\n| Слово | Частота |\n|-------|---------|\n")
        for word, cnt in ud['word_counter'].most_common(10):
            md_lines.append(f"| {word} | {cnt} |\n")

        # Топ-10 самых длинных сообщений
        md_lines.append("\n### Топ-10 самых длинных сообщений\n| Длина | Дата | Текст (начало) |\n|-------|------|----------------|\n")
        # Сообщения в куче хранятся как (длина, timestamp, текст). Сортируем по убыванию длины
        longest = sorted(ud['longest_messages'], key=lambda x: x[0], reverse=True)
        for length, ts, snippet in longest[:10]:
            date_str = datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M') if ts else 'неизвестно'
            # Экранируем символы для Markdown (труба, скобки)
            snippet_clean = snippet.replace('|', '\\|').replace('\n', ' ')
            md_lines.append(f"| {length} | {date_str} | {snippet_clean} |\n")
        md_lines.append("\n---\n")

    # Сохраняем
    with open(output_md_path, 'w', encoding='utf-8') as f:
        f.writelines(md_lines)

    print(f"✅ Готово! Расширенный отчёт сохранён в: {output_md_path}")

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Использование: python chat_stats_advanced.py <путь_к_json> [путь_к_md]")
    else:
        input_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else None
        analyze_telegram_json(input_file, output_file)