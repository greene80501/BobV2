"""Flask web application for GrayBench UI."""

import logging
from pathlib import Path

from flask import Flask

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_web_app() -> Flask:
    """Create the GrayBench web UI Flask application."""
    from graybench.db.engine import init_db
    init_db()

    app = Flask(__name__,
                static_folder=str(STATIC_DIR),
                static_url_path="/static")

    # Register API routes
    from graybench.web.api import api_bp
    app.register_blueprint(api_bp, url_prefix="/api")

    @app.route("/")
    def index():
        return app.send_static_file("index.html")

    @app.route("/health")
    def health():
        return {"status": "ok"}

    log.info("GrayBench web UI initialized")
    return app
