# WB DRR Bot — чистка ключей WB по ДРР

Telegram-бот для Clicki. Принимает выгрузку WB «Топ поисковых кластеров», спрашивает цену товара
и норму ДРР и раскладывает кластеры на 🔴 возможно удалить / 🟡 работать / 🟢 норма /
⚪ мало данных, с итогами по каждому блоку. Отдаёт сводку в чат и Excel с минус-фразами.
Все анализы хранятся в истории: их можно открыть, скачать Excel и пересчитать с другими параметрами.

Подробное ТЗ и правила расчёта — в [CLAUDE.md](CLAUDE.md).

## Настройка

1. Создай бота у [@BotFather](https://t.me/BotFather) и получи токен.
2. Узнай свой Telegram user_id (например, у @userinfobot).
3. Скопируй `.env.example` в `.env` и заполни:

```
BOT_TOKEN=123456:ABC...
ALLOWED_USER_IDS=111111111,222222222
ADMIN_IDS=111111111
DATA_DIR=data
```

## Доступ

- `ALLOWED_USER_IDS` пустой — бот открыт для всех.
- `ALLOWED_USER_IDS` заполнен — доступ только этим ID, остальным «Нет доступа».
- `ADMIN_IDS` — админы. У них всегда есть доступ и команда `/stats`: пользователи, анализы
  за сутки и неделю, место на диске. Не-админам команда не отвечает.
- Каждый пользователь видит только свою историю.

## Ограничения

Значения задаются в [config.py](config.py):

| Параметр | По умолчанию | Что делает |
|---|---|---|
| `MAX_FILE_SIZE` | 10 МБ | файл больше — отказ |
| `MAX_CLUSTER_ROWS` | 20 000 | строк в листе кластеров больше — отказ |
| `MAX_ANALYSES_PER_DAY` | 20 | анализов (включая пересчёты) за последние 24 часа |
| `FLOOD_INTERVAL` | 1 с | не чаще одного сообщения от пользователя, лишние отбрасываются |
| `FILE_TTL_DAYS` | 60 | выгрузки старше удаляются раз в сутки; записи в истории остаются, а «📥 Excel» и «🔁 Пересчитать» пишут «Файл устарел, загрузи заново» |

Ошибки обработки пишутся в лог с user_id. Пользователь получает короткое сообщение без трейсбека.

## Локальный запуск

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows; на Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Тесты:

```bash
pytest -q
```

Фикстура `tests/fixtures/Топ_поисковых_кластеров_2026-09-17_-_2026-09-23.xlsx` нужна для тестов
на реальных данных. Если её нет, эти тесты пропускаются.

## Деплой на сервер (Ubuntu 24.04, Docker)

Бот работает в Docker-контейнере и перезапускается сам после сбоя и перезагрузки сервера
(`restart: unless-stopped`). База, выгрузки и логи лежат на сервере в папках `data/` и `logs/`
рядом с `docker-compose.yml` — пересборка и обновление их не трогают. Время в логах и базе —
московское (`TZ=Europe/Moscow`).

### 1. Собрать архив на Windows

```powershell
powershell -ExecutionPolicy Bypass -File make_deploy.ps1
```

Получится `deploy.zip` в папке проекта: код, `assets/`, `data/` (база с историей) и `.env`.
Без `.venv`, `.git`, `logs` и кешей. **В архиве токен бота и телефоны пользователей** —
не пересылайте его в открытые чаты.

### 2. Установить Docker на сервер (один раз)

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2 unzip sqlite3
sudo systemctl enable --now docker
```

### 3. Перенести и запустить

С Windows (подставьте свой адрес сервера):

```powershell
scp deploy.zip root@SERVER_IP:/opt/
```

На сервере:

```bash
sudo mkdir -p /opt/wb-drr-bot
sudo unzip -o /opt/deploy.zip -d /opt/wb-drr-bot
cd /opt/wb-drr-bot
sudo docker compose up -d --build
```

**Перед запуском на сервере остановите бота на своём компьютере.** Два экземпляра с одним
токеном мешают друг другу (Telegram отдаёт сообщения только одному, в логе — `Conflict`).
На Windows:

```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | ? CommandLine -like '*main.py*' | % { Stop-Process -Id $_.ProcessId }
```

### 4. Проверить и смотреть логи

```bash
cd /opt/wb-drr-bot
sudo docker compose ps                 # статус: Up
sudo docker compose logs -f --tail 50  # вывод бота в реальном времени (Ctrl+C — выйти)
tail -f logs/bot.log                   # файл лога
sudo docker compose exec bot date      # время в контейнере — московское
```

В логе должна быть строка `Run polling for bot @…`.

### 5. Управление

```bash
sudo docker compose restart   # перезапуск (например, после правки .env)
sudo docker compose stop      # остановить
sudo docker compose start     # запустить снова
```

### 6. Обновить код

Соберите новый `deploy.zip` на Windows и загрузите на сервер (`scp`, как в п. 3). На сервере
распакуйте **без `data/` и `.env`** — иначе база на сервере затрётся старой копией с компьютера:

```bash
cd /opt/wb-drr-bot
sudo unzip -o /opt/deploy.zip -x 'data/*' '.env' -d /opt/wb-drr-bot
sudo docker compose up -d --build
```

Видео, PDF и логотип в `assets/` подключены с хоста: их можно просто заменить файлом и сделать
`sudo docker compose restart`, без пересборки.

### 7. Бэкап базы

Разовый бэкап (безопасно при работающем боте — SQLite делает согласованный снимок):

```bash
cd /opt/wb-drr-bot
sudo mkdir -p backups
sudo sqlite3 data/bot.db ".backup 'backups/bot-$(date +%F).db'"
```

Ежедневный бэкап в 03:00 с хранением 30 дней:

```bash
sudo crontab -e
```

и добавить строку:

```
0 3 * * * cd /opt/wb-drr-bot && mkdir -p backups && sqlite3 data/bot.db ".backup 'backups/bot-$(date +\%F).db'" && find backups -name 'bot-*.db' -mtime +30 -delete
```

Скачать бэкап на Windows:

```powershell
scp root@SERVER_IP:/opt/wb-drr-bot/backups/bot-*.db .
```

Восстановить из бэкапа:

```bash
cd /opt/wb-drr-bot
sudo docker compose stop
sudo cp backups/bot-2026-10-01.db data/bot.db
sudo docker compose start
```

## Деплой через systemd (Linux)

```bash
sudo useradd -r -m -d /opt/wb-drr-bot wbbot
sudo -u wbbot git clone <repo> /opt/wb-drr-bot   # или скопировать файлы
cd /opt/wb-drr-bot
sudo -u wbbot python3 -m venv .venv
sudo -u wbbot .venv/bin/pip install -r requirements.txt
sudo -u wbbot cp .env.example .env && sudo -u wbbot nano .env
sudo cp deploy/wb-drr-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wb-drr-bot
journalctl -u wb-drr-bot -f        # или tail -f logs/bot.log
```

## Структура

```
core/       чистая логика без Telegram: parser, analyzer, relevance, report
storage/    SQLite (db.py) и файлы выгрузок (files.py)
bot/        aiogram: handlers, keyboards, states, validators, service (связка core + storage)
tests/      pytest, включая сквозной прогон сценариев бота без Telegram
```

Параметры расчёта (`WORK_SHARE`, стоп-слова, пресеты ДРР, размер страницы истории) —
в [config.py](config.py).

## Хранение

- `data/bot.db` — SQLite: `users`, `uploads`, `analyses`.
- `data/uploads/{user_id}/{upload_id}.xlsx` — исходные выгрузки.
- Excel-отчёт не хранится: он пересобирается из выгрузки и параметров при нажатии «📥 Excel».
- Удаление анализа стирает файл, только если на него больше не ссылается ни один анализ.

## Известные ограничения

- FSM хранится в памяти: после перезапуска незавершённый диалог «Новый анализ» нужно начать заново.
  История и настройки хранятся в SQLite и не теряются.
- Анти-флуд и FSM живут в памяти процесса: при нескольких экземплярах бота нужен общий Redis.
