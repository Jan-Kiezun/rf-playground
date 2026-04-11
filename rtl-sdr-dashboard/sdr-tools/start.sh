#!/bin/bash
# Start a minimal HTTP health-check server on port 8080 so the backend can probe
# device connectivity WITHOUT connecting to rtl_tcp (which exits on client disconnect).
python3 - <<'EOF' &
import socket, threading

def handle(conn):
    try:
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
    finally:
        conn.close()

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", 8080))
srv.listen(10)
while True:
    conn, _ = srv.accept()
    threading.Thread(target=handle, args=(conn,), daemon=True).start()
EOF

# Run rtl_tcp in a restart loop so it recovers if it exits for any reason.
while true; do
    echo "Starting rtl_tcp on 0.0.0.0:1234..."
    rtl_tcp -a 0.0.0.0 -p 1234 || true
    echo "rtl_tcp exited, restarting in 1s..."
    sleep 1
done
