import os
import signal
import sys
from flask import Flask, jsonify, cli
import mount
import time
import threading
import logging

app = Flask(__name__)
MOUNTING_COMPLETE = False


@app.route("/health", methods=["GET"])
def health():
    """Returns 200 if all S3 buckets are ready, 503 otherwise."""
    if MOUNTING_COMPLETE:
        return jsonify({"status": "ready"}), 200
    return jsonify({"status": "mounting"}), 503


@app.route("/shutdown", methods=["POST"])
def shutdown():
    """Endpoint for the main container to signal it is finished."""
    print("Shutdown requested via API endpoint.")

    def kill_delay():
        time.sleep(1)
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=kill_delay).start()
    return "Cleanup initiated", 200


def cleanup_and_exit(signum, frame):
    """Signal handler to ensure S3fs is unmounted before the container dies."""
    print(f"\nSignal {signum} received. Cleaning up mounts...")
    mount.umount(aliases)
    print("Exiting.")
    sys.exit(0)


def main_logic():
    """Runs the initial mounting sequence."""
    global MOUNTING_COMPLETE
    print("Initializing S3 mounts...")
    global aliases
    aliases = mount.mount()
    MOUNTING_COMPLETE = True
    print("S3 system ready.")


if __name__ == "__main__":
    # disable logging and banner view of flask itself
    cli.show_server_banner = lambda *args: None
    logging.getLogger("werkzeug").disabled = True

    signal.signal(signal.SIGINT, cleanup_and_exit)
    signal.signal(signal.SIGTERM, cleanup_and_exit)

    main_logic()

    print("Starting Datastore API on port 5000...")
    app.run(host="0.0.0.0", port=5000)
