import logging
import sys

class MayaLogHandler(logging.StreamHandler):
    """Custom handler to send logs to Maya Script Editor"""
    def __init__(self):
        super().__init__()
        self.muted = False
        
    def emit(self, record):
        if self.muted:
            return
            
        try:
            msg = self.format(record)
            print(msg)  # This goes to Maya Script Editor
        except Exception:
            self.handleError(record)
    
    def set_muted(self, muted):
        """Set mute state"""
        self.muted = muted

class LoggerManager:
    """Centralized logger management"""
    def __init__(self):
        self._logger = None
        self._handler = None
        self._setup_done = False
    
    def setup_logger(self):
        """Set up the logger for Blue Steel"""
        if self._setup_done:
            return self._logger
            
        self._logger = logging.getLogger("blue_steel")
        self._logger.setLevel(logging.DEBUG)

        # Clear existing handlers
        if self._logger.hasHandlers():
            self._logger.handlers.clear()

        # Add Maya handler
        self._handler = MayaLogHandler()
        self._handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(message)s')
        self._handler.setFormatter(formatter)
        self._logger.addHandler(self._handler)

        # PREVENT PROPAGATION - this stops Maya's default logging
        self._logger.propagate = False
        
        self._setup_done = True
        return self._logger
    
    def mute(self):
        """Mute the logger"""
        if self._handler:
            self._handler.set_muted(True)
    
    def unmute(self):
        """Unmute the logger"""
        if self._handler:
            self._handler.set_muted(False)
    
    def is_muted(self):
        """Check if muted"""
        return self._handler.muted if self._handler else False
    
    def set_level(self, level):
        """Set logging level"""
        if self._logger:
            self._logger.setLevel(level)
        if self._handler:
            self._handler.setLevel(level)

# Global logger manager
_logger_manager = LoggerManager()

def setup_logger():
    """Set up the logger for Blue Steel"""
    return _logger_manager.setup_logger()

def mute_logger():
    """Mute the logger"""
    _logger_manager.mute()

def unmute_logger():
    """Unmute the logger"""
    _logger_manager.unmute()

def is_logger_muted():
    """Check if logger is muted"""
    return _logger_manager.is_muted()

def set_logger_level(level):
    """Set logger level"""
    _logger_manager.set_level(level)

def remove_logger_handlers():
    """Remove all handlers from the logger"""
    logger = _logger_manager._logger
    if logger:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()