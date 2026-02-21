# AI Studio Proxy API: Ubuntu VPS + UV (без Docker)

## 1) Подготовка Ubuntu VPS

```bash
sudo apt update
sudo apt install -y curl git python3 python3-venv ca-certificates \
  libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdrm2 libgbm1 \
  libgtk-3-0 libnss3 libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 \
  libxrandr2 libpango-1.0-0 libpangocairo-1.0-0 fonts-liberation
```

Установить `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv --version
```

## 2) Установка проекта через UV

```bash
git clone https://github.com/MasuRii/AIstudioProxyAPI.git
cd AIstudioProxyAPI
uv venv --python python3
uv pip install -r requirements-uv.txt
uv run playwright install firefox
uv run camoufox fetch
cp .env.example .env
```

## 3) Настройка `.env` (прокси + ретраи)

Минимально:

```env
UNIFIED_PROXY_CONFIG=http://<user>:<pass>@<host>:<port>
RETRY_ON_403=true
RETRY_ON_403_MAX_ATTEMPTS=3
```

## 4) Авторизация (обязательно)

На сервере должен быть готовый auth-файл в `auth_profiles/active/*.json`.

Если файл уже есть на другом хосте, перенеси его через `scp`:

```bash
scp /path/to/profile.json user@your-vps:/home/user/AIstudioProxyAPI/auth_profiles/active/
```

## 5) Запуск без Docker

Обычный запуск:

```bash
uv run python launch_camoufox.py --headless
```

Запуск с явным флагом ретраев `403`:

```bash
uv run python launch_camoufox.py --headless --retry-on-403 --retry-on-403-max-attempts 3
```

## 6) Что делают ретраи `403`

- Ретраи включаются флагом `--retry-on-403` или через `.env` (`RETRY_ON_403=true`).
- Количество попыток задается `--retry-on-403-max-attempts` или `RETRY_ON_403_MAX_ATTEMPTS`.
- При `403`/`forbidden` выполняется повтор запроса с backoff.
- Если все попытки исчерпаны, вернется ошибка.

## 7) Автозапуск на VPS через systemd

Создай юнит:

```bash
sudo tee /etc/systemd/system/aistudio-proxy.service > /dev/null <<'EOF'
[Unit]
Description=AI Studio Proxy API (UV)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/AIstudioProxyAPI
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/ubuntu/.local/bin/uv run python launch_camoufox.py --headless --retry-on-403 --retry-on-403-max-attempts 3
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

Применить:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now aistudio-proxy
sudo systemctl status aistudio-proxy
journalctl -u aistudio-proxy -f
```

## 8) Проверка API

```bash
curl -sS http://127.0.0.1:2048/health
curl -sS http://127.0.0.1:2048/v1/models
```

Обычный streaming:

```bash
curl -N -sS -X POST 'http://127.0.0.1:2048/v1/chat/completions' \
  -H 'Content-Type: application/json' \
  --data-raw '{"model":"gemini-3-pro-preview","stream":true,"messages":[{"role":"user","content":"скажи привет"}]}'
```

Streaming только с финальным текстом:

```bash
curl -N -sS -X POST 'http://127.0.0.1:2048/v1/chat/completions' \
  -H 'Content-Type: application/json' \
  --data-raw '{"model":"gemini-3-pro-preview","stream":true,"stream_final_message_only":true,"messages":[{"role":"user","content":"скажи привет"}]}'
```
