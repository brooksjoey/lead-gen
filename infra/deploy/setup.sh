#!/usr/bin/env bash
set -euo pipefail

COMPOSE_VERSION="2.20.3"
COMPOSE_BIN="$HOME/.docker/cli-plugins/docker-compose"
if [ ! -x "$COMPOSE_BIN" ]; then
  mkdir -p "$(dirname "$COMPOSE_BIN")"
  curl -fsSL "https://github.com/docker/compose/releases/download/v${COMPOSE_VERSION}/docker-compose-linux-x86_64" -o "$COMPOSE_BIN"
  chmod +x "$COMPOSE_BIN"
fi

# Ensure docker compose v2 is symlinked for easy access
if ! command -v docker-compose >/dev/null 2>&1; then
  sudo ln -sf "$COMPOSE_BIN" /usr/local/bin/docker-compose
fi

echo "Docker Compose v${COMPOSE_VERSION} is available"

echo "Creating systemd service unit..."
cat <<'EOF' | sudo tee /etc/systemd/system/leadgen.service >/dev/null
[Unit]
Description=LeadGen stack
Requires=docker.service
After=docker.service

[Service]
WorkingDirectory=$(pwd)
EnvironmentFile=$(pwd)/.env
ExecStartPre=/usr/bin/docker compose pull
ExecStart=/usr/bin/docker compose up --build
ExecStop=/usr/bin/docker compose down
Restart=always

[Install]
WantedBy=multi-user.target
EOF

echo "Reloading systemd daemon"
sudo systemctl daemon-reload
sudo systemctl enable --now leadgen.service

echo "Deployment helper finished"
