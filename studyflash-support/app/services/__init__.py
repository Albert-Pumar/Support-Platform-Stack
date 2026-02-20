# This file makes app/services a package and exports the ws_manager singleton
from app.services.ws_manager import ws_manager

__all__ = ["ws_manager"]
