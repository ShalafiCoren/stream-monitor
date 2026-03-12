#!/bin/bash
## Deploy Stream Monitor on jarvis (Linux/WSL)
## Run from stream-monitor/ directory: bash deploy/install-jarvis.sh

set -e

INSTALL_DIR="/home/usuario535/services/stream-monitor"
SERVICE_NAME="stream-monitor"

echo "=== Stream Monitor — Deploy to jarvis ==="

# Copy files
echo "[1/5] Copying files to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"/{sensors,engine,actions,deploy}
cp monitor.py requirements.txt "$INSTALL_DIR/"
cp sensors/*.py "$INSTALL_DIR/sensors/"
cp engine/*.py "$INSTALL_DIR/engine/"
cp actions/*.py "$INSTALL_DIR/actions/"
cp config.jarvis.yaml "$INSTALL_DIR/config.yaml"

# Install dependencies
echo "[2/5] Installing Python dependencies..."
cd "$INSTALL_DIR"
pip3 install -r requirements.txt

# Test single pass
echo "[3/5] Testing single pass..."
python3 monitor.py --once --debug

# Install systemd service
echo "[4/5] Installing systemd service..."
sudo cp deploy/stream-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl start "$SERVICE_NAME"

# Verify
echo "[5/5] Verifying..."
sleep 3
sudo systemctl status "$SERVICE_NAME" --no-pager

echo ""
echo "=== Deploy complete ==="
echo "  Config:  $INSTALL_DIR/config.yaml"
echo "  Log:     $INSTALL_DIR/stream-monitor.log"
echo "  Status:  sudo systemctl status $SERVICE_NAME"
echo "  Restart: sudo systemctl restart $SERVICE_NAME"
echo "  Log:     journalctl -u $SERVICE_NAME -f"
