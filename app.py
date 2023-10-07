# (c) Jigarvarma2005
# Always welcome of pull requests

from gevent import monkey
monkey.patch_all()

import os
import time
import json
from flask import Flask, render_template, request, send_from_directory
from flask_socketio import SocketIO, emit
import threading
import aria2p
from requests import get as rget
from subprocess import Popen as subprocess_run
from geventwebsocket.handler import WebSocketHandler
from gevent.pywsgi import WSGIServer
import platform

app = Flask(__name__)
socketio = SocketIO(app, async_mode='gevent', logger=True, engineio_logger=True)
DOWNLOADS_FOLDER = 'downloads'  # Specify the downloads folder path


def aria_start():
    operating_system = platform.system()
    if operating_system == 'Windows':
        cmd = "aria.bat"
    else:
        cmd = "chmod a+x aria.sh; ./aria.sh"
    subprocess_run(cmd, shell=True)
    time.sleep(5) # wait for 5sec to start aria2c
    aria2 = aria2p.API(
        aria2p.Client(host="http://localhost", port=6800, secret="")
    )
    return aria2

aria2 = aria_start()


# Background thread to monitor and emit download status
def monitor_downloads():
    while True:
        downloads = aria2.get_downloads()
        status_items = []
        for download in downloads:
            download_status = download.status if download.total_length != download.completed_length else "complete"
            if (download_status == "complete" and download.name.strip().upper().startswith("[METADATA]")) or download.name == "undefined":
                continue
            if download_status == 'complete':
                file_dir = os.path.join(DOWNLOADS_FOLDER, download.name)
                if not os.path.exists(file_dir):
                    continue
            progress_data = {
            "status": download_status,
            "progress": download.progress,
            'totalLength': download.total_length_string(),
            'completedLength': download.completed_length_string(),
            'download_id': download.gid,
            'eta': download.eta_string(),
            'name': download.name
            }
            if download_status != "complete":
                progress_data['downloadSpeed'] = download.download_speed_string()
            status_items.append(progress_data)
        socketio.emit('status_update', {"status_items": status_items}, namespace='/')
        socketio.sleep(7)  # Refresh status every 7 seconds

# Start the background thread when the server is running
@socketio.on('connect', namespace='/')
def start_monitoring_thread():
    print("connect")

# Route to serve the index.html page
@app.route('/')
def index():
    return render_template('index.html')

# WebSocket event handlers
@socketio.on('download_magnet', namespace='/')
def download_magnet(data):
    download_dir = os.path.join(os.getcwd(), DOWNLOADS_FOLDER)
    options = {
        'dir': download_dir,
    }
    magnet_link = data['magnet_link']
    download = aria2.add_magnet(magnet_link, options=options)
    emit('download_started', {'download_id': download.gid, 'file_name': download.name}, broadcast=True)

@socketio.on('disconnect', namespace='/')
def test_disconnect():
    print('Client disconnected')

@app.route('/download/<path:filename>')
def download_file(filename):
    # Get the absolute path of the requested file
    file_path = os.path.join(DOWNLOADS_FOLDER, filename)

    # Check if the file path is within the downloads folder
    if os.path.isdir(file_path):
        # Get the list of files in the folder
        files = os.listdir(file_path)
        return render_template('folders.html', folder=filename, files=files)
    elif os.path.exists(file_path):
        # Send the file for download
        return send_from_directory(DOWNLOADS_FOLDER, filename, as_attachment=True)
    else:
        return render_template('forbidden.html')


if __name__ == '__main__':
    # Start the background thread for monitoring downloads
    threading.Thread(target=monitor_downloads, daemon=True).start()
    http_server = WSGIServer(('0.0.0.0', 5000), app, handler_class=WebSocketHandler)
    http_server.serve_forever()