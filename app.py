"""Entrypoint for local execution and WSGI servers."""
from criticard import create_app
from criticard.chat import socketio

app = create_app()

if __name__ == "__main__":
    socketio.run(app, host=app.config["HOST"], port=app.config["PORT"],
                 debug=app.config["DEBUG"], allow_unsafe_werkzeug=True)
