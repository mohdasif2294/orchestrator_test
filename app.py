"""Flask application factory."""

import sqlite3
import os
from flask import Flask
import config
from utils.logger import get_logger

logger = get_logger(__name__)


def init_db(app: Flask) -> None:
    """Create database tables from schema.sql if they do not exist.

    Args:
        app: The Flask application instance.
    """
    schema_path = os.path.join(os.path.dirname(__file__), "database", "schema.sql")
    with open(schema_path, "r") as f:
        schema = f.read()

    conn = sqlite3.connect(config.DATABASE)
    try:
        conn.executescript(schema)
        conn.commit()
        logger.info("Database initialized: %s", config.DATABASE)
    finally:
        conn.close()


def create_app() -> Flask:
    """Create and configure the Flask application.

    Returns:
        A configured Flask app instance.
    """
    app = Flask(__name__)

    # Initialize the database
    init_db(app)

    # Register blueprints
    from routes.workflow_routes import workflow_bp
    from routes.execution_routes import execution_bp
    from routes.step_routes import step_bp

    app.register_blueprint(workflow_bp)
    app.register_blueprint(execution_bp)
    app.register_blueprint(step_bp)

    logger.info("Application created — blueprints registered")
    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
